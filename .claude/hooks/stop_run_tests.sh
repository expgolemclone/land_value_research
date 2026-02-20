#!/bin/bash
# Stop hook: Run test suite when Claude finishes responding.
# Only runs if Python source files were modified.

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$PROJECT_DIR" || exit 0

# Skip if no Python files were changed (staged or unstaged)
if ! git diff --name-only HEAD 2>/dev/null | grep -q '\.py$' && \
   ! git diff --name-only --cached 2>/dev/null | grep -q '\.py$'; then
  exit 0
fi

output=$(python -m pytest tests/ -v --tb=short 2>&1)
exit_code=$?

if [ $exit_code -ne 0 ]; then
  echo "TESTS FAILED — fix before committing:" >&2
  echo "$output" | tail -30 >&2
  exit 2
fi

exit 0
