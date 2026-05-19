"""Display-time screening configuration for land value ranking."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from src.config import PROJECT_ROOT


@dataclass(frozen=True, slots=True)
class ScreeningConfig:
    config_path: Path
    strategy_path: Path


def _resolve_project_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def load_screening_config(path: Path | str) -> ScreeningConfig:
    config_path = _resolve_project_path(str(path))
    with config_path.open("rb") as f:
        raw = tomllib.load(f)

    strategy_path_raw = raw.get("strategy_path")
    if not isinstance(strategy_path_raw, str) or not strategy_path_raw.strip():
        raise ValueError(f"screening config must define non-empty strategy_path: {config_path}")

    strategy_path = _resolve_project_path(strategy_path_raw.strip())
    if not strategy_path.exists():
        raise FileNotFoundError(f"screening strategy file not found: {strategy_path}")

    return ScreeningConfig(config_path=config_path, strategy_path=strategy_path)
