"""Codex 起動時にソースコードの読み取り権限を剥奪するコンテキストマネージャ."""

import stat
from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# import に必要なため除外
_SRC_ALLOW = {"geocode_tokyo.py", "__init__.py"}

_BUILD_FILES = [
    "Cargo.toml",
    "Cargo.lock",
    "pyproject.toml",
    "flake.nix",
    "flake.lock",
    "uv.lock",
    "rust-toolchain.toml",
    ".gitattributes",
]


def _find_targets() -> list[Path]:
    targets: list[Path] = []
    # トップレベル .py
    for p in PROJECT_ROOT.glob("*.py"):
        targets.append(p)
    # src/ 内（allowlist 除外）
    for p in PROJECT_ROOT.joinpath("src").rglob("*.py"):
        if p.name not in _SRC_ALLOW:
            targets.append(p)
    # rust_src, scripts, tests
    for d in ["rust_src", "scripts", "tests"]:
        dp = PROJECT_ROOT / d
        if dp.exists():
            for p in dp.rglob("*"):
                if p.is_file():
                    targets.append(p)
    # ビルド設定
    for name in _BUILD_FILES:
        p = PROJECT_ROOT / name
        if p.is_file():
            targets.append(p)
    # .claude/
    claude_dir = PROJECT_ROOT / ".claude"
    if claude_dir.exists():
        for p in claude_dir.rglob("*"):
            if p.is_file():
                targets.append(p)
    return targets


@contextmanager
def codex_lockdown():
    """ファイル権限を 000 にロックし、ブロック終了時に復元する."""
    locked: list[tuple[Path, int]] = []
    try:
        for p in _find_targets():
            orig = stat.S_IMODE(p.stat().st_mode)
            locked.append((p, orig))
            p.chmod(0o000)
        print(f"[lockdown] {len(locked)} files locked")
        yield
    finally:
        for p, orig in locked:
            try:
                p.chmod(orig)
            except OSError:
                pass
        print(f"[lockdown] {len(locked)} files restored")
