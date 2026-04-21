"""Spawns `claude -p ...` subprocesses on the host and returns parsed JSON.

This is the ONLY path from bridge to Claude. OAuth tokens are read by the CLI
itself from the user's Keychain / ~/.claude/ — the bridge never sees them.
"""
from __future__ import annotations

import asyncio
import json
import shlex
from dataclasses import dataclass


class ClaudeSubprocessError(Exception):
    pass


@dataclass
class ClaudeResult:
    content: str
    model: str
    cost_usd: float
    duration_ms: int
    raw: dict


class ClaudeClient:
    def __init__(self, cli_path: str, timeout_seconds: int) -> None:
        self._cli = cli_path
        self._timeout = timeout_seconds

    async def complete(
        self,
        *,
        prompt: str,
        model: str,
        system: str | None = None,
        max_turns: int | None = None,
        allowed_tool_names: list[str] | None = None,
    ) -> ClaudeResult:
        """Invoke `claude -p` with --output-format=json. Returns parsed result.

        Notes on system prompt authority: `--append-system-prompt` does NOT
        replace the CLI's default system prompt. If a malicious/bogus
        CLAUDE.md is discoverable in the working dir it could outrank META.
        The bridge subprocess runs with cwd=$BRIDGE_WORKDIR (a dir we control)
        so nothing lower wins the ancestor-walk. Document this in OPERATIONS.
        """
        argv = [self._cli, "-p", prompt, "--output-format", "json", "--model", model]
        if system:
            argv += ["--append-system-prompt", system]
        if max_turns is not None:
            argv += ["--max-turns", str(int(max_turns))]
        if allowed_tool_names is not None:
            # Empty list = no tools at all (tightest). The CLI may ignore this
            # flag depending on version; verify with `claude -p --help`.
            argv += ["--allowed-tools", ",".join(allowed_tool_names) or "NONE"]

        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise ClaudeSubprocessError(
                f"claude subprocess timed out after {self._timeout}s: {shlex.join(argv)}"
            ) from None

        if proc.returncode != 0:
            raise ClaudeSubprocessError(
                f"claude exited {proc.returncode}: {stderr.decode(errors='replace')[:500]}"
            )

        try:
            parsed = json.loads(stdout.decode())
        except json.JSONDecodeError as e:
            raise ClaudeSubprocessError(
                f"could not parse claude output as JSON: {e}; first 200 chars: "
                f"{stdout.decode(errors='replace')[:200]}"
            ) from e

        return ClaudeResult(
            content=str(parsed.get("result", "")),
            model=str(parsed.get("model", model)),
            cost_usd=float(parsed.get("total_cost_usd", 0.0)),
            duration_ms=int(parsed.get("duration_ms", 0)),
            raw=parsed,
        )
