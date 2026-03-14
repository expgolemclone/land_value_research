#!/usr/bin/env bash
set -euo pipefail

# Codex を .md ファイルのみ見えるワークスペースで起動するラッパー。
# git sparse-checkout worktree を使い、コードファイルへのアクセスを制限する。

REPO_ROOT="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)"
WORKTREE_DIR="${REPO_ROOT}/.codex-worktree"

cleanup() {
    if [ -d "$WORKTREE_DIR" ]; then
        git -C "$REPO_ROOT" worktree remove --force "$WORKTREE_DIR" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# 既存の worktree があれば削除
cleanup

# detached HEAD で worktree 作成
git -C "$REPO_ROOT" worktree add --detach "$WORKTREE_DIR" HEAD --quiet

# sparse-checkout: .md ファイルのみ
git -C "$WORKTREE_DIR" sparse-checkout set --no-cone '*.md'

# worktree 内に Codex プロジェクト設定を配置
mkdir -p "${WORKTREE_DIR}/.codex"
cat > "${WORKTREE_DIR}/.codex/config.toml" <<'TOML'
sandbox_mode = "workspace-write"
approval_policy = "on-request"
TOML

# Codex を worktree ディレクトリで起動（引数をパススルー）
codex -C "$WORKTREE_DIR" "$@"
