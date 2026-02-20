#!/bin/bash
# PostToolUse hook: Auto-run ruff check & format after file edits.

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$PROJECT_DIR" || exit 0

# Only lint Python files — skip if the edited file isn't .py
json_input=$(cat)
file_path=$(echo "$json_input" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path','') or d.get('tool_result',{}).get('filePath',''))" 2>/dev/null)

if [ -n "$file_path" ] && [[ ! "$file_path" =~ \.py$ ]]; then
  exit 0
fi

ruff check --fix --quiet . 2>&1
ruff format --quiet . 2>&1

exit 0
