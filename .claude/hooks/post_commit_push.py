#!/usr/bin/env python3
"""PostToolUse hook: Auto-push after every git commit."""

import json
import os
import re
import subprocess
import sys


def main() -> None:
    data = json.load(sys.stdin)
    command = data.get("tool_input", {}).get("command", "")
    if not command:
        return

    # Only trigger on git commit commands
    if not re.search(r"git\s+commit\b", command):
        return

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )

    # Check if there are commits ahead of remote
    result = subprocess.run(
        ["git", "rev-list", "--count", "@{upstream}..HEAD"],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    ahead = result.stdout.strip()
    if not ahead or ahead == "0":
        return

    push_result = subprocess.run(
        ["git", "push"],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    if push_result.returncode != 0:
        print(f"AUTO-PUSH FAILED after commit:\n{push_result.stderr}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
