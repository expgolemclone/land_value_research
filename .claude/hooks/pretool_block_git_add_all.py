#!/usr/bin/env python3
"""PreToolUse hook: Block 'git add .' and 'git add -A/--all'.

Enforces semantic-unit staging per CLAUDE.md workflow rules.
"""

import json
import re
import sys


def main() -> None:
    data = json.load(sys.stdin)
    command = data.get("tool_input", {}).get("command", "")
    if not command:
        return

    if re.search(r"git\s+add\s+(\.|(-A|--all))(\s|$)", command):
        json.dump(
            {
                "decision": "block",
                "reason": (
                    "BLOCKED: 'git add .' / 'git add -A' is prohibited."
                    " Stage files individually by semantic unit of change."
                ),
            },
            sys.stdout,
        )


if __name__ == "__main__":
    main()
