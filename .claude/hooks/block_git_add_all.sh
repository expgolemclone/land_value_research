#!/bin/bash
# PreToolUse hook: Block "git add ." and "git add -A/--all"
# Enforces semantic-unit staging per CLAUDE.md workflow rules.

json_input=$(cat)
command=$(echo "$json_input" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))" 2>/dev/null)

if [ -z "$command" ]; then
  exit 0
fi

# Block: git add . | git add -A | git add --all
if echo "$command" | grep -qE 'git\s+add\s+(\.|(-A|--all))\b'; then
  echo "BLOCKED: 'git add .' / 'git add -A' is prohibited. Stage files individually by semantic unit of change." >&2
  exit 2
fi

exit 0
