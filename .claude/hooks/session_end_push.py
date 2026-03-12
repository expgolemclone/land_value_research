#!/usr/bin/env python3
"""SessionEnd hook: Push all commits to remote on session end."""

import os
import subprocess


def main() -> None:
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )

    result = subprocess.run(
        ["git", "rev-list", "--count", "@{upstream}..HEAD"],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    ahead = result.stdout.strip()
    if ahead and ahead != "0":
        subprocess.run(["git", "push"], cwd=project_dir)


if __name__ == "__main__":
    main()
