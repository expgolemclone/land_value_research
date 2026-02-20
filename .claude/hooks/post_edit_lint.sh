#!/bin/bash
# PostToolUse hook: Auto-run ruff check & format after file edits.

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$PROJECT_DIR" || exit 0

# Only lint Python files — skip if the edited file isn't .py
json_input=$(cat)
file_path=$(echo "$json_input" | jq -r '.tool_input.file_path // .tool_result.filePath // empty')

if [ -n "$file_path" ] && [[ ! "$file_path" =~ \.py$ ]]; then
  exit 0
fi

ruff check --fix --quiet . 2>&1
ruff format --quiet . 2>&1

exit 0
