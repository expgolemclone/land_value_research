#!/bin/bash
# PostToolUse hook: Auto-push after every git commit.
# Ensures commits are immediately pushed to remote.

json_input=$(cat)
command=$(echo "$json_input" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))" 2>/dev/null)

if [ -z "$command" ]; then
  exit 0
fi

# Only trigger on git commit commands
if ! echo "$command" | grep -qE 'git\s+commit\b'; then
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$PROJECT_DIR" || exit 0

# Check if there are commits ahead of remote
ahead=$(git rev-list --count @{upstream}..HEAD 2>/dev/null)
if [ -n "$ahead" ] && [ "$ahead" -gt 0 ]; then
  push_output=$(git push 2>&1)
  push_exit=$?
  if [ $push_exit -ne 0 ]; then
    echo "AUTO-PUSH FAILED after commit:" >&2
    echo "$push_output" >&2
    exit 2
  fi
fi

exit 0
