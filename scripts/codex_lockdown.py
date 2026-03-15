"""Codex 起動時にソースコードの読み取り権限を剥奪するコンテキストマネージャ."""

from __future__ import annotations

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


def _find_targets(
    target_codes: list[str] | None = None,
    mode: str | None = None,
) -> tuple[list[Path], list[Path]]:
    """ロック対象のファイルとディレクトリ制限対象を返す.

    Returns:
        (files_to_lock, dirs_to_restrict)
        files_to_lock: chmod 0o000 にするファイル
        dirs_to_restrict: chmod 0o111 にするディレクトリ (ls 不可、直接パスアクセスのみ可)
    """
    targets: list[Path] = []
    dirs_to_restrict: list[Path] = []
    codes = set(target_codes) if target_codes else set()

    # --- 既存のロック対象 ---

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

    # --- 追加: docs/ ディレクトリ制限 ---
    docs_dir = PROJECT_ROOT / "docs"
    if docs_dir.exists():
        dirs_to_restrict.append(docs_dir)
        for p in docs_dir.glob("*.md"):
            # 対象企業の docs は書き込み/参照用にロックしない
            if codes and p.stem in codes:
                continue
            targets.append(p)

    # --- 追加: data/output/ ディレクトリ制限 ---
    output_dir = PROJECT_ROOT / "data" / "output"
    if output_dir.exists():
        dirs_to_restrict.append(output_dir)

    # --- 追加: data/ranking/ ファイルロック ---
    ranking_html = PROJECT_ROOT / "data" / "ranking" / "ranking_market_cap_ratio.html"
    if ranking_html.is_file():
        targets.append(ranking_html)

    # --- 追加: 対象外スキルのロック ---
    if mode:
        other_skill = "resolve-address" if mode == "split-address" else "split-address"
        for base in [".agents", ".claude"]:
            skill_md = PROJECT_ROOT / base / "skills" / other_skill / "SKILL.md"
            if skill_md.is_file():
                targets.append(skill_md)

    return targets, dirs_to_restrict


@contextmanager
def codex_lockdown(
    target_codes: list[str] | None = None,
    mode: str | None = None,
):
    """ファイル権限をロックし、ブロック終了時に復元する.

    Args:
        target_codes: 対象企業の証券コード。これらの企業固有ファイルはロックしない。
        mode: 実行モード ("split-address" / "resolve-address")。対象外スキルをロックする。
    """
    locked: list[tuple[Path, int]] = []
    try:
        targets, dirs_to_restrict = _find_targets(target_codes, mode)
        # ファイルロック (0o000)
        for p in targets:
            orig = stat.S_IMODE(p.stat().st_mode)
            locked.append((p, orig))
            p.chmod(0o000)
        # ディレクトリ制限 (0o111: ls 不可、直接パスアクセスのみ可)
        for d in dirs_to_restrict:
            orig = stat.S_IMODE(d.stat().st_mode)
            locked.append((d, orig))
            d.chmod(0o111)
        print(f"[lockdown] {len(locked)} items locked")
        yield
    finally:
        for p, orig in locked:
            try:
                p.chmod(orig)
            except OSError:
                pass
        print(f"[lockdown] {len(locked)} items restored")
