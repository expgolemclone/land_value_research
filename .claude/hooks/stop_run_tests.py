#!/usr/bin/env python3
"""Stop hook: Run test suite when Claude finishes responding."""

import os
import subprocess
import sys


def main() -> None:
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )

    venv_python = os.path.join(project_dir, ".venv", "bin", "python")
    result = subprocess.run(
        [venv_python, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        output = result.stdout + result.stderr
        lines = output.splitlines()
        tail = "\n".join(lines[-30:])
        print(f"TESTS FAILED — fix before committing:\n{tail}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
