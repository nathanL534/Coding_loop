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
from .manifest import verify as manifest_verify
from .policy import Policy

log = logging.getLogger("bridge")


# ---------- Request / response models ----------


class Message(BaseModel):
    role: str
    content: Any


class CompleteRequest(BaseModel):
    """Container -> bridge.

    Note: `is_autonomous` is INTENTIONALLY ABSENT — autonomy is decided by the
    bridge, not the container. If `inbox_token` is a valid token the bridge
    handed out via /v1/inbox, this request is considered user-initiated;
    otherwise it is autonomous.
    """

    prompt: str = Field(..., min_length=1, max_length=200_000)
    system: str | None = Field(None, max_length=20_000)
    model: str | None = None
    tools: list[dict] | None = None
    max_turns: int | None = Field(None, ge=1, le=20)
    task_id: str | None = Field(None, max_length=200)
    inbox_token: str | None = Field(None, max_length=64)
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
        self.audit: AuditLog | None = None
        self.kill: KillSwitch | None = None
        self.policy: Policy | None = None
        self.claude: ClaudeClient | None = None
        self.approvals: ApprovalQueue | None = None
        self.notify_callable = None         # host-only: Telegram send
        self.inbox_queue = None             # set by telegram wiring
        self.valid_inbox_tokens: set[str] = set()
        self.repo_root: Path | None = None


def _load_config() -> cfg.BridgeConfig:
    path_env = os.environ.get("BRIDGE_CONFIG")
    if path_env:
        return cfg.load(Path(path_env))
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
    state.repo_root = c.safety_dir.parent  # safety/ is under repo root

    # Startup manifest check: refuse to boot if protected files are tampered.
    _enforce_manifest(state)

    app = FastAPI(title="claude-bridge", version="0.1.0")
    app.state.bridge = state

    def get_state() -> State:
        return state

    def _is_user_initiated(body: CompleteRequest) -> bool:
        """Autonomy is decided here, not by the container.

        A request is "user-initiated" iff it carries an inbox_token the bridge
        issued for a real Telegram message AND hasn't been consumed yet. The
        token is single-use so the container can't spend it on multiple
        expensive calls.
        """
        if not body.inbox_token:
            return False
        if body.inbox_token in state.valid_inbox_tokens:
            state.valid_inbox_tokens.discard(body.inbox_token)
            return True
        return False

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
        is_autonomous = not _is_user_initiated(body)

        try:
            s.kill.check()
        except KillSwitchActive as e:
            await s.audit.write(event="reject.kill", request_id=req_id, task_id=body.task_id, error=str(e))
            raise HTTPException(503, detail=str(e))

        # Manifest re-verify on every call so a runtime tamper is caught before spend.
        tampered = _manifest_diffs(s)
        if tampered:
            await s.audit.write(
                event="reject.manifest",
                request_id=req_id,
                task_id=body.task_id,
                error=",".join(tampered),
            )
            raise HTTPException(403, detail=f"protected files modified: {tampered}")

        decision = s.policy.evaluate(
            requested_model=body.model,
            container_system=body.system,
            requested_tools=body.tools,
            is_autonomous=is_autonomous,
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

        # Reserve-then-settle: increment spend by estimate pre-call to avoid two
        # concurrent requests both passing the check and blowing the cap.
        try:
            await s.budget.reserve(body.cost_estimate_usd)
        except BudgetExceeded as e:
            await s.audit.write(event="reject.budget", request_id=req_id, task_id=body.task_id, error=str(e))
            raise HTTPException(402, detail=str(e))

        # Re-check kill switch right before spawning subprocess (close the TOCTOU).
        try:
            s.kill.check()
        except KillSwitchActive as e:
            await s.budget.settle(reserved=body.cost_estimate_usd, actual=0.0)
            await s.audit.write(event="reject.kill_toctou", request_id=req_id, task_id=body.task_id, error=str(e))
            raise HTTPException(503, detail=str(e))

        try:
            result = await s.claude.complete(
                prompt=body.prompt,
                model=decision.model,
                system=decision.system_prompt,
                max_turns=body.max_turns,
                allowed_tool_names=decision.allowed_tool_names,
            )
        except ClaudeSubprocessError as e:
            await s.budget.settle(reserved=body.cost_estimate_usd, actual=0.0)
            duration_ms = int((time.monotonic() - t0) * 1000)
            await s.audit.write(
                event="error.claude",
                request_id=req_id,
                task_id=body.task_id,
                error=str(e),
                duration_ms=duration_ms,
            )
            raise HTTPException(502, detail="claude subprocess failed")

        await s.budget.settle(reserved=body.cost_estimate_usd, actual=result.cost_usd)
        duration_ms = int((time.monotonic() - t0) * 1000)
        await s.audit.write(
            event="ok.complete",
            request_id=req_id,
            task_id=body.task_id,
            model=result.model,
            messages=[{"role": "user", "content": body.prompt}],
            cost_usd=result.cost_usd,
            duration_ms=duration_ms,
            extra={"autonomous": is_autonomous, "tools": decision.allowed_tool_names},
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
        """Long-poll. Returns next Telegram msg + a single-use inbox_token the
        container echoes back on the derived /v1/complete to prove user-initiation."""
        try:
            s.kill.check()
        except KillSwitchActive as e:
            raise HTTPException(503, detail=str(e))
        q = s.inbox_queue
        if q is None:
            raise HTTPException(503, detail="telegram gateway not attached")
        try:
            import asyncio as _asyncio
            m = await _asyncio.wait_for(q.get(), timeout=max(0.1, min(timeout, 60.0)))
        except TimeoutError:
            return {"msg": None}
        # Track the token so the container can later redeem it.
        if getattr(m, "inbox_token", ""):
            s.valid_inbox_tokens.add(m.inbox_token)
        return {
            "msg": {
                "chat_id": m.chat_id,
                "user_id": m.user_id,
                "text": m.text,
                "ts": m.ts,
                "inbox_token": getattr(m, "inbox_token", ""),
            }
        }

    return app


def _enforce_manifest(state: State) -> None:
    """Raise on startup if protected files don't match the manifest."""
    if state.config is None or state.repo_root is None:
        return
    manifest_path = state.config.safety_dir / "manifest.sha256"
    if not manifest_path.exists():
        log.warning("manifest.sha256 not found at %s — cannot verify protected files", manifest_path)
        return
    diffs = manifest_verify(state.repo_root, manifest_path, list(state.config.protected_files))
    if diffs:
        raise RuntimeError(f"safety manifest mismatch, refusing to start: {diffs}")


def _manifest_diffs(state: State) -> list[str]:
    if state.config is None or state.repo_root is None:
        return []
    manifest_path = state.config.safety_dir / "manifest.sha256"
    if not manifest_path.exists():
        return []
    return manifest_verify(state.repo_root, manifest_path, list(state.config.protected_files))


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
