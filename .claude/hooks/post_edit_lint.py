#!/usr/bin/env python3
"""PostToolUse hook: Auto-run ruff check & format after file edits."""

import json
import os
import shutil
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

    if sys.platform == "win32":
        ruff = os.path.join(project_dir, ".venv", "Scripts", "ruff.exe")
    else:
        ruff = os.path.join(project_dir, ".venv", "bin", "ruff")

    devnull = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}

    if os.path.isfile(ruff):
        subprocess.run([ruff, "check", "--fix", "--quiet", project_dir], cwd=project_dir, **devnull)
        subprocess.run([ruff, "format", "--quiet", project_dir], cwd=project_dir, **devnull)
    elif shutil.which("nix"):
        subprocess.run(
            [
                "nix", "develop", project_dir, "--command", "bash", "-c",
                f"ruff check --fix --quiet '{project_dir}' && ruff format --quiet '{project_dir}'",
            ],
            cwd=project_dir,
            **devnull,
        )


if __name__ == "__main__":
    main()
