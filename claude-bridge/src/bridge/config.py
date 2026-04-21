"""Load bridge config from TOML + safety YAMLs."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class BudgetConfig:
    daily_usd_cap: float
    per_wake_usd_cap: float
    per_request_usd_cap: float
    per_request_timeout_seconds: int
    requests_per_hour: int
    requests_per_minute_burst: int
    default_model: str
    allowed_models: tuple[str, ...]
    denied_for_autonomous: tuple[str, ...]


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    allowed_user_id: int
    mode: str = "polling"


@dataclass(frozen=True)
class ClaudeConfig:
    cli_path: str
    timeout_seconds: int


@dataclass(frozen=True)
class BridgeConfig:
    socket_path: Path
    state_dir: Path
    safety_dir: Path
    budget: BudgetConfig
    telegram: TelegramConfig
    claude: ClaudeConfig
    allowlist: dict[str, Any] = field(default_factory=dict)
    protected_files: tuple[str, ...] = ()


def _expand(p: str) -> Path:
    return Path(os.path.expanduser(p)).resolve()


def load_budget(safety_dir: Path) -> BudgetConfig:
    data = yaml.safe_load((safety_dir / "budget.yaml").read_text())
    rl = data["rate_limits"]
    models = data["models"]
    return BudgetConfig(
        daily_usd_cap=float(data["daily_usd_cap"]),
        per_wake_usd_cap=float(data["per_wake_usd_cap"]),
        per_request_usd_cap=float(data["per_request_usd_cap"]),
        per_request_timeout_seconds=int(data["per_request_timeout_seconds"]),
        requests_per_hour=int(rl["requests_per_hour"]),
        requests_per_minute_burst=int(rl["requests_per_minute_burst"]),
        default_model=str(models["default"]),
        allowed_models=tuple(models["allowed"]),
        denied_for_autonomous=tuple(models.get("denied_for_autonomous", ())),
    )


def load_allowlist(safety_dir: Path) -> dict[str, Any]:
    return yaml.safe_load((safety_dir / "allowlist.yaml").read_text()) or {}


def load_protected_files(safety_dir: Path) -> tuple[str, ...]:
    path = safety_dir / "protected-files.txt"
    if not path.exists():
        return ()
    lines = path.read_text().splitlines()
    return tuple(
        line.strip() for line in lines if line.strip() and not line.strip().startswith("#")
    )


def load(config_path: Path) -> BridgeConfig:
    with config_path.open("rb") as f:
        data = tomllib.load(f)

    br = data["bridge"]
    safety_dir = _expand(br["safety_dir"])
    state_dir = _expand(br["state_dir"])
    state_dir.mkdir(parents=True, exist_ok=True)

    return BridgeConfig(
        socket_path=Path(br["socket_path"]),
        state_dir=state_dir,
        safety_dir=safety_dir,
        budget=load_budget(safety_dir),
        telegram=TelegramConfig(
            bot_token=data["telegram"]["bot_token"],
            allowed_user_id=int(data["telegram"]["allowed_user_id"]),
            mode=data["telegram"].get("mode", "polling"),
        ),
        claude=ClaudeConfig(
            cli_path=data["claude"]["cli_path"],
            timeout_seconds=int(data["claude"]["timeout_seconds"]),
        ),
        allowlist=load_allowlist(safety_dir),
        protected_files=load_protected_files(safety_dir),
    )
