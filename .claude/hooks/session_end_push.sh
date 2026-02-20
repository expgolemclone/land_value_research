#!/bin/bash
# SessionEnd hook: Push all commits to remote on session end.

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$PROJECT_DIR" || exit 0

# Only push if there are local commits ahead of remote
ahead=$(git rev-list --count @{upstream}..HEAD 2>/dev/null)
if [ -n "$ahead" ] && [ "$ahead" -gt 0 ]; then
  git push 2>&1
fi

exit 0
