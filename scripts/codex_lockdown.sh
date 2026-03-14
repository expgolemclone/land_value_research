#!/usr/bin/env bash
# Codex 起動前にコードファイルの読み取り権限を剥奪し、
# 終了後に復元するラッパースクリプト。
#
# 使い方: ./scripts/codex_lockdown.sh [codex args...]

set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

LOCKDOWN_LIST=$(mktemp)
trap 'restore_permissions; rm -f "$LOCKDOWN_LIST"' EXIT INT TERM

find_targets() {
    cd "$PROJECT_DIR"
    # トップレベルの .py ファイル
    find . -maxdepth 1 -name '*.py' -printf '%P\n' 2>/dev/null
    # src/ 内（geocode_tokyo.py と __init__.py は除外 — import に必要）
    find src -name '*.py' \
        ! -name 'geocode_tokyo.py' \
        ! -name '__init__.py' \
        -printf '%P\n' 2>/dev/null
    # Rust ソース・スクリプト・テスト
    find rust_src scripts tests -type f -printf '%P\n' 2>/dev/null
    # ビルド設定
    for f in Cargo.toml Cargo.lock pyproject.toml flake.nix flake.lock \
             uv.lock rust-toolchain.toml .gitattributes; do
        [ -f "$f" ] && echo "$f"
    done
    # Claude Code 設定
    find .claude -type f -printf '%P\n' 2>/dev/null
}

lock_permissions() {
    find_targets | sort -u | while IFS= read -r f; do
        if [ -f "$PROJECT_DIR/$f" ]; then
            echo "$f" >> "$LOCKDOWN_LIST"
            chmod 000 "$PROJECT_DIR/$f"
        fi
    done
    echo "[lockdown] $(wc -l < "$LOCKDOWN_LIST") files locked"
}

restore_permissions() {
    if [ -f "$LOCKDOWN_LIST" ]; then
        while IFS= read -r f; do
            chmod 644 "$PROJECT_DIR/$f" 2>/dev/null || true
        done < "$LOCKDOWN_LIST"
        echo "[lockdown] permissions restored"
    fi
}

lock_permissions
cd "$PROJECT_DIR"
codex "$@"
