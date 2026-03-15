#!/usr/bin/env python3
"""PostToolUse hook: Auto-run ruff check & format after file edits."""

import json
import os
import subprocess
import sys


def main() -> None:
    data = json.load(sys.stdin)
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "") or data.get("tool_result", {}).get("filePath", "")

    # Only lint Python files
    if file_path and not file_path.endswith(".py"):
        return

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )

    subprocess.run(
        [
            "nix",
            "develop",
            project_dir,
            "--command",
            "bash",
            "-c",
            f"ruff check --fix --quiet '{project_dir}' && ruff format --quiet '{project_dir}'",
        ],
        cwd=project_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


if __name__ == "__main__":
    main()
