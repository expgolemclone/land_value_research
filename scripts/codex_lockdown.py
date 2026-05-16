"""Codex 起動時にソースコードの読み取り権限を剥奪するコンテキストマネージャ."""

from __future__ import annotations

import atexit
import json
import logging
import signal
import stat
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import ADDRESS_OVERRIDES_PATH, DEFAULT_OUTPUT_DIR  # noqa: E402

_log = logging.getLogger(__name__)

# import に必要なため除外
_SRC_ALLOW = {"geocode_tokyo.py", "__init__.py", "pdf_extract.py"}

# claude CLI の動作に必要なため除外
_CLAUDE_ALLOW = {"SKILL.md", "settings.json", "settings.local.json"}

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

_LOCKDOWN_STATE_FILE = PROJECT_ROOT / "split-address" / "research_logs" / ".lockdown_state.json"


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
    # .claude/ and .agents/ (claude CLI 動作に必要なファイルとフックは除外)
    for d in [".claude", ".agents"]:
        dp = PROJECT_ROOT / d
        if dp.exists():
            for p in dp.rglob("*"):
                if p.is_file() and p.name not in _CLAUDE_ALLOW and "hooks" not in p.parts:
                    targets.append(p)

    # --- 追加: split-address/ ファイル個別ロック ---
    docs_dir = PROJECT_ROOT / "split-address"
    if docs_dir.exists():
        for p in docs_dir.glob("*.md"):
            # 対象企業の split-address は書き込み/参照用にロックしない
            if codes and p.stem in codes:
                continue
            targets.append(p)

    # --- 追加: split-address/research_logs/ 既存ログファイルのロック ---
    research_logs_dir = PROJECT_ROOT / "split-address" / "research_logs"
    if research_logs_dir.exists():
        for p in research_logs_dir.iterdir():
            if p.is_file() and p.name != _LOCKDOWN_STATE_FILE.name:
                targets.append(p)

    # --- 追加: data/output/ ディレクトリ制限 ---
    output_dir = DEFAULT_OUTPUT_DIR
    if output_dir.exists():
        dirs_to_restrict.append(output_dir)

    # --- 追加: address_overrides.yaml ロック ---
    overrides_yaml = ADDRESS_OVERRIDES_PATH
    if overrides_yaml.is_file():
        targets.append(overrides_yaml)

    # --- 追加: .git/ ディレクトリ制限 (git コマンドをブロック) ---
    git_dir = PROJECT_ROOT / ".git"
    if git_dir.exists():
        dirs_to_restrict.append(git_dir)

    return targets, dirs_to_restrict


def _save_lockdown_state(locked: list[tuple[Path, int]]) -> None:
    """ロック状態をファイルに永続化する."""
    _LOCKDOWN_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "locked_at": datetime.now().isoformat(),
        "items": [{"path": str(p), "orig_mode": mode} for p, mode in locked],
    }
    _LOCKDOWN_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _delete_lockdown_state() -> None:
    """ロック状態ファイルを削除する."""
    try:
        _LOCKDOWN_STATE_FILE.unlink(missing_ok=True)
    except OSError:
        _log.debug("ロック状態ファイルの削除に失敗", exc_info=True)


def recover_stale_lockdown() -> bool:
    """前回の異常終了で残ったロック状態を復旧する.

    Returns:
        True if recovery was performed.
    """
    if not _LOCKDOWN_STATE_FILE.exists():
        return False

    print("[lockdown] 前回の異常終了を検出. パーミッション復旧中...")
    try:
        state = json.loads(_LOCKDOWN_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"[lockdown] 状態ファイルの読み込みに失敗: {e}")
        _delete_lockdown_state()
        return False

    restored = 0
    for item in state.get("items", []):
        p = Path(item["path"])
        orig_mode = item["orig_mode"]
        try:
            p.chmod(orig_mode)
            restored += 1
        except OSError:
            _log.debug("パーミッション復旧に失敗: %s", p, exc_info=True)

    _delete_lockdown_state()
    print(f"[lockdown] {restored} items restored (前回ロック時刻: {state.get('locked_at', '不明')})")
    return True


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
    # 前回の残骸を復旧
    recover_stale_lockdown()

    locked: list[tuple[Path, int]] = []
    prev_handlers: dict[int, object] = {}

    def _emergency_restore(*_args: object) -> None:
        """シグナルハンドラ: パーミッション復旧して終了."""
        for p, orig in locked:
            try:
                p.chmod(orig)
            except OSError:
                _log.debug("緊急復旧でchmodに失敗: %s", p, exc_info=True)
        _delete_lockdown_state()
        print(f"\n[lockdown] {len(locked)} items restored (signal)")
        sys.exit(1)

    try:
        targets, dirs_to_restrict = _find_targets(target_codes, mode)

        # 元パーミッションを収集
        items: list[tuple[Path, int]] = []
        for p in targets:
            items.append((p, stat.S_IMODE(p.stat().st_mode)))
        for d in dirs_to_restrict:
            items.append((d, stat.S_IMODE(d.stat().st_mode)))

        # ロック状態を永続化（ロック実行前に保存）
        _save_lockdown_state(items)

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

        # シグナルハンドラ登録
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            try:
                prev_handlers[sig] = signal.signal(sig, _emergency_restore)
            except (OSError, ValueError):
                _log.debug("シグナルハンドラ登録に失敗: %s", sig, exc_info=True)

        # atexit 登録
        atexit.register(_emergency_restore)

        print(f"[lockdown] {len(locked)} items locked")
        yield
    finally:
        # パーミッション復旧
        for p, orig in locked:
            try:
                p.chmod(orig)
            except OSError:
                _log.debug("パーミッション復旧に失敗: %s", p, exc_info=True)
        _delete_lockdown_state()

        # シグナルハンドラ復元
        for sig, handler in prev_handlers.items():
            try:
                signal.signal(sig, handler)
            except (OSError, ValueError):
                _log.debug("シグナルハンドラ復元に失敗: %s", sig, exc_info=True)

        # atexit 解除
        atexit.unregister(_emergency_restore)

        print(f"[lockdown] {len(locked)} items restored")
