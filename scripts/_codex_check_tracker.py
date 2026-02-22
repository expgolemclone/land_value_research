"""Codex split-address check count tracker.

Manages per-company check counts in config/codex_check_status.yaml.
Called from PowerShell scripts to track how many times a company has
been investigated by the split-address skill.

Usage:
    uv run python scripts/_codex_check_tracker.py get <code>
    uv run python scripts/_codex_check_tracker.py increment <code>
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

TRACKER_FILE = Path(__file__).resolve().parents[1] / "config" / "codex_check_status.yaml"


def _load() -> dict[str, int]:
    if not TRACKER_FILE.exists():
        return {}
    with open(TRACKER_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return {}
    return {str(k): int(v) for k, v in data.items() if isinstance(v, int)}


def _save(data: dict[str, int]) -> None:
    TRACKER_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Codex split-address 調査回数トラッカー\n", "# key: 証券コード (文字列), value: 調査回数 (整数)\n"]
    for code in sorted(data, key=lambda c: int(c) if c.isdigit() else 0):
        lines.append(f"'{code}': {data[code]}\n")
    with open(TRACKER_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(lines)


def get(code: str) -> int:
    return _load().get(code, 0)


def increment(code: str) -> int:
    data = _load()
    data[code] = data.get(code, 0) + 1
    _save(data)
    return data[code]


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: uv run python scripts/_codex_check_tracker.py {get|increment} <code>", file=sys.stderr)
        return 2

    command = argv[1]
    code = argv[2]

    if command == "get":
        print(get(code))
    elif command == "increment":
        print(increment(code))
    else:
        print(f"unknown command: {command}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
