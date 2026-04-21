"""FastAPI bridge. Listens on a Unix socket (host). Never on a TCP port in production."""
from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import config as cfg
from .approval import ApprovalQueue, ApprovalTimeout
from .audit import AuditLog
from .budget import BudgetExceeded, BudgetTracker
from .claude_client import ClaudeClient, ClaudeSubprocessError
from .killswitch import KillSwitch, KillSwitchActive
from .policy import Policy, PolicyViolation
from .ratelimit import RateLimiter, RateLimitExceeded

log = logging.getLogger("bridge")


# ---------- Request / response models ----------


class Message(BaseModel):
    role: str
    content: Any


class CompleteRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=200_000)
    system: str | None = Field(None, max_length=20_000)
    model: str | None = None
    tools: list[dict] | None = None
    max_turns: int | None = Field(None, ge=1, le=20)
    task_id: str | None = Field(None, max_length=200)
    is_autonomous: bool = True
    cost_estimate_usd: float = Field(0.05, ge=0.0, le=1.0)


class CompleteResponse(BaseModel):
    request_id: str
    content: str
    model: str
    cost_usd: float
    duration_ms: int


class ApproveRequestBody(BaseModel):
    action: str = Field(..., max_length=200)
    reason: str = Field(..., max_length=2000)
    cost_estimate_usd: float = Field(0.0, ge=0.0, le=1000.0)
    timeout_seconds: int = Field(3600, ge=10, le=86400)


class ApproveResponse(BaseModel):
    approved: bool


class NotifyBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


class BudgetResponse(BaseModel):
    day: str
    spent_today_usd: float
    spent_this_wake_usd: float
    daily_cap_usd: float
    per_wake_cap_usd: float
    per_request_cap_usd: float


# ---------- App state ----------


class State:
    def __init__(self) -> None:
        self.config: cfg.BridgeConfig | None = None
        self.budget: BudgetTracker | None = None
        self.rate: RateLimiter | None = None
        self.audit: AuditLog | None = None
        self.kill: KillSwitch | None = None
        self.policy: Policy | None = None
        self.claude: ClaudeClient | None = None
        self.approvals: ApprovalQueue | None = None
        self.notify_callable = None  # set by telegram wiring


def _load_config() -> cfg.BridgeConfig:
    path_env = os.environ.get("BRIDGE_CONFIG")
    if path_env:
        return cfg.load(Path(path_env))
    # fallback for local tests — callers should inject via BRIDGE_CONFIG
    return cfg.load(Path("config.toml"))


def build_app(config: cfg.BridgeConfig | None = None) -> FastAPI:
    c = config or _load_config()
    state = State()
    state.config = c
    state.budget = BudgetTracker(
        state_path=c.state_dir / "budget.json",
        daily_cap_usd=c.budget.daily_usd_cap,
        per_wake_cap_usd=c.budget.per_wake_usd_cap,
        per_request_cap_usd=c.budget.per_request_usd_cap,
    )
    state.rate = RateLimiter(
        per_hour=c.budget.requests_per_hour,
        burst_per_minute=c.budget.requests_per_minute_burst,
    )
    state.audit = AuditLog(path=c.state_dir / "audit.log")
    state.kill = KillSwitch(flag_path=c.state_dir / "pause")
    state.policy = Policy(
        default_model=c.budget.default_model,
        allowed_models=c.budget.allowed_models,
        denied_for_autonomous=c.budget.denied_for_autonomous,
    )
    state.claude = ClaudeClient(
        cli_path=c.claude.cli_path, timeout_seconds=c.claude.timeout_seconds
    )
    state.approvals = ApprovalQueue()

    app = FastAPI(title="claude-bridge", version="0.1.0")
    app.state.bridge = state

    def get_state() -> State:
        return state

    # ---------- endpoints ----------

    @app.get("/v1/health")
    async def health(s: State = Depends(get_state)) -> dict:
        snap = await s.budget.snapshot() if s.budget else None
        return {
            "ok": True,
            "kill_switch": s.kill.is_active() if s.kill else False,
            "budget": snap.__dict__ if snap else None,
        }

    @app.get("/v1/budget", response_model=BudgetResponse)
    async def budget(s: State = Depends(get_state)) -> BudgetResponse:
        snap = await s.budget.snapshot()
        return BudgetResponse(**snap.__dict__)

    @app.post("/v1/complete", response_model=CompleteResponse)
    async def complete(body: CompleteRequest, s: State = Depends(get_state)) -> CompleteResponse:
        req_id = str(uuid.uuid4())
        t0 = time.monotonic()
        try:
            s.kill.check()
        except KillSwitchActive as e:
            await s.audit.write(event="reject.kill", request_id=req_id, task_id=body.task_id, error=str(e))
            raise HTTPException(503, detail=str(e))

        try:
            await s.rate.check()
        except RateLimitExceeded as e:
            await s.audit.write(event="reject.rate", request_id=req_id, task_id=body.task_id, error=str(e))
            raise HTTPException(429, detail=str(e))

        decision = s.policy.evaluate(
            requested_model=body.model,
            container_system=body.system,
            requested_tools=body.tools,
            is_autonomous=body.is_autonomous,
        )
        if not decision.allowed:
            await s.audit.write(
                event="reject.policy",
                request_id=req_id,
                task_id=body.task_id,
                error=decision.reason,
                model=decision.model,
            )
            raise HTTPException(403, detail=decision.reason or "policy denied")

        try:
            await s.budget.check_can_spend(body.cost_estimate_usd)
        except BudgetExceeded as e:
            await s.audit.write(event="reject.budget", request_id=req_id, task_id=body.task_id, error=str(e))
            raise HTTPException(402, detail=str(e))

        try:
            result = await s.claude.complete(
                prompt=body.prompt,
                model=decision.model,
                system=decision.system_prompt,
                max_turns=body.max_turns,
            )
        except ClaudeSubprocessError as e:
            duration_ms = int((time.monotonic() - t0) * 1000)
            await s.audit.write(
                event="error.claude",
                request_id=req_id,
                task_id=body.task_id,
                error=str(e),
                duration_ms=duration_ms,
            )
            raise HTTPException(502, detail="claude subprocess failed")

        await s.budget.record(result.cost_usd)
        duration_ms = int((time.monotonic() - t0) * 1000)
        await s.audit.write(
            event="ok.complete",
            request_id=req_id,
            task_id=body.task_id,
            model=result.model,
            messages=[{"role": "user", "content": body.prompt}],
            cost_usd=result.cost_usd,
            duration_ms=duration_ms,
        )
        return CompleteResponse(
            request_id=req_id,
            content=result.content,
            model=result.model,
            cost_usd=result.cost_usd,
            duration_ms=duration_ms,
        )

    @app.post("/v1/approve-required", response_model=ApproveResponse)
    async def approve(body: ApproveRequestBody, s: State = Depends(get_state)) -> ApproveResponse:
        try:
            s.kill.check()
        except KillSwitchActive as e:
            raise HTTPException(503, detail=str(e))
        try:
            approved = await s.approvals.request(
                action=body.action,
                reason=body.reason,
                cost_estimate_usd=body.cost_estimate_usd,
                timeout_seconds=body.timeout_seconds,
            )
        except ApprovalTimeout as e:
            raise HTTPException(408, detail=str(e))
        return ApproveResponse(approved=approved)

    @app.post("/v1/notify")
    async def notify(body: NotifyBody, s: State = Depends(get_state)) -> dict:
        try:
            s.kill.check()
        except KillSwitchActive as e:
            raise HTTPException(503, detail=str(e))
        if s.notify_callable is None:
            raise HTTPException(503, detail="telegram gateway not attached")
        await s.notify_callable(body.text)
        return {"ok": True}

    @app.get("/v1/inbox")
    async def inbox(timeout: float = 25.0, s: State = Depends(get_state)) -> dict:
        """Long-poll. Returns the next inbound Telegram message, or {msg: null} after timeout."""
        try:
            s.kill.check()
        except KillSwitchActive as e:
            raise HTTPException(503, detail=str(e))
        q = getattr(s, "inbox_queue", None)
        if q is None:
            raise HTTPException(503, detail="telegram gateway not attached")
        try:
            import asyncio as _asyncio

            m = await _asyncio.wait_for(q.get(), timeout=max(0.1, min(timeout, 60.0)))
        except TimeoutError:
            return {"msg": None}
        return {
            "msg": {
                "chat_id": m.chat_id,
                "user_id": m.user_id,
                "text": m.text,
                "ts": m.ts,
            }
        }

    return app


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    c = _load_config()
    app = build_app(c)
    uvicorn.run(
        app,
        uds=str(c.socket_path),
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    run()
