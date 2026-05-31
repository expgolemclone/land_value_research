from pathlib import Path

import pytest

import src.screening_config as screening_config_mod
from src.screening_config import load_screening_config


def test_load_screening_config_resolves_project_relative_strategy_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    strategy_path = project_root / "strategies" / "net_cash_fcf.toml"
    strategy_path.parent.mkdir()
    strategy_path.write_text("[[filters]]\n", encoding="utf-8")
    config_path = project_root / "config" / "screening.toml"
    config_path.parent.mkdir()
    config_path.write_text('strategy_path = "strategies/net_cash_fcf.toml"\n', encoding="utf-8")
    monkeypatch.setattr(screening_config_mod, "PROJECT_ROOT", project_root)

    config = load_screening_config("config/screening.toml")

    assert config.config_path == config_path
    assert config.strategy_path == strategy_path


def test_load_screening_config_requires_strategy_path(tmp_path: Path) -> None:
    config_path = tmp_path / "screening.toml"
    config_path.write_text('title = "missing"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="strategy_path"):
        load_screening_config(config_path)
