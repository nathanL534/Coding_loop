"""Telegram bot glued to the bridge.

Invariants:
- Bot token lives ONLY on the host (this process). Never mounted into container.
- `allowed_user_id` check on EVERY incoming update. Non-match = silent drop.
- Inbound user messages are pushed onto an in-memory queue the container pulls via
  GET /v1/inbox (long-polled). Outbound from container = POST /v1/notify.
- Approval resolutions (/yes /no <id>) resolve pending ApprovalQueue entries.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass
from typing import Awaitable, Callable

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .approval import ApprovalQueue
from .killswitch import KillSwitch

log = logging.getLogger("bridge.telegram")


@dataclass
class InboxMessage:
    chat_id: int
    user_id: int
    text: str
    ts: float
    inbox_token: str = ""   # bridge-issued; container echoes back to prove user-initiation


class TelegramGateway:
    def __init__(
        self,
        *,
        bot_token: str,
        allowed_user_id: int,
        approvals: ApprovalQueue,
        kill_switch: KillSwitch,
        budget_snapshot: "Callable[[], Awaitable[dict]] | None" = None,
    ) -> None:
        if not bot_token or bot_token == "PASTE_BOT_TOKEN_HERE":
            raise ValueError("telegram.bot_token is not configured")
        if allowed_user_id <= 0:
            raise ValueError("telegram.allowed_user_id must be > 0")

        self._allowed = allowed_user_id
        self._approvals = approvals
        self._kill = kill_switch
        self._budget_snapshot = budget_snapshot
        self._inbox: asyncio.Queue[InboxMessage] = asyncio.Queue(maxsize=1000)
        self._app: Application = Application.builder().token(bot_token).build()
        self._wire_handlers()

    def _wire_handlers(self) -> None:
        self._app.add_handler(CommandHandler("start", self._on_start))
        self._app.add_handler(CommandHandler("pause", self._on_pause))
        self._app.add_handler(CommandHandler("resume", self._on_resume))
        self._app.add_handler(CommandHandler("yes", self._on_yes))
        self._app.add_handler(CommandHandler("no", self._on_no))
        self._app.add_handler(CommandHandler("budget", self._on_budget))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))

    def _is_allowed(self, update: Update) -> bool:
        u = update.effective_user
        return u is not None and u.id == self._allowed

    async def _reject_silently(self, update: Update) -> None:
        log.warning(
            "dropped update from unauthorized user id=%s chat=%s",
            update.effective_user.id if update.effective_user else None,
            update.effective_chat.id if update.effective_chat else None,
        )

    async def _on_start(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update):
            return await self._reject_silently(update)
        await update.message.reply_text(
            "coding-loop bridge online. Send a message to talk to the agent.\n"
            "Commands: /pause /resume /yes <id> /no <id> /budget"
        )

    async def _on_text(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update):
            return await self._reject_silently(update)
        msg = update.message
        if msg is None or msg.text is None:
            return
        try:
            self._inbox.put_nowait(
                InboxMessage(
                    chat_id=msg.chat_id,
                    user_id=update.effective_user.id,
                    text=msg.text,
                    ts=msg.date.timestamp(),
                    inbox_token=secrets.token_urlsafe(24),
                )
            )
        except asyncio.QueueFull:
            await msg.reply_text("inbox is full; try again in a minute")

    async def _on_pause(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update):
            return await self._reject_silently(update)
        self._kill.activate()
        await update.message.reply_text("kill switch ACTIVE. bridge will refuse all requests.")

    async def _on_resume(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update):
            return await self._reject_silently(update)
        self._kill.clear()
        await update.message.reply_text("kill switch cleared. bridge accepting requests.")

    async def _on_yes(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update):
            return await self._reject_silently(update)
        await self._resolve(update, ctx, "yes")

    async def _on_no(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update):
            return await self._reject_silently(update)
        await self._resolve(update, ctx, "no")

    async def _resolve(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, decision: str) -> None:
        if not ctx.args:
            await update.message.reply_text(f"usage: /{decision} <request_id>")
            return
        req_id = ctx.args[0]
        ok = await self._approvals.resolve(req_id, decision)  # type: ignore[arg-type]
        await update.message.reply_text(
            f"resolved {req_id} -> {decision}" if ok else f"no pending request {req_id}"
        )

    async def _on_budget(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_allowed(update):
            return await self._reject_silently(update)
        if self._budget_snapshot is None:
            await update.message.reply_text("budget snapshot not wired")
            return
        snap = await self._budget_snapshot()
        await update.message.reply_text(
            f"today: ${snap['spent_today_usd']:.3f} / ${snap['daily_cap_usd']:.2f}\n"
            f"wake:  ${snap['spent_this_wake_usd']:.3f} / ${snap['per_wake_cap_usd']:.2f}"
        )

    async def send(self, text: str) -> None:
        """Outbound: bridge /v1/notify handler calls this."""
        await self._app.bot.send_message(chat_id=self._allowed, text=text)

    async def push_approval(self, *, request_id: str, action: str, reason: str, cost_estimate_usd: float) -> None:
        """Push a pending approval to the user so they can /yes &lt;id&gt; or /no &lt;id&gt;."""
        text = (
            f"APPROVAL NEEDED\n"
            f"action: {action}\n"
            f"reason: {reason}\n"
            f"cost est: ${cost_estimate_usd:.3f}\n"
            f"id: {request_id}\n\n"
            f"/yes {request_id}  or  /no {request_id}"
        )
        await self._app.bot.send_message(chat_id=self._allowed, text=text)

    def inbox(self) -> asyncio.Queue[InboxMessage]:
        return self._inbox

    async def start(self) -> None:
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

    async def stop(self) -> None:
        await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()
