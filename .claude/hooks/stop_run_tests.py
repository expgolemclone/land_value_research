#!/usr/bin/env python3
"""Stop hook: Run test suite when Claude finishes responding."""

import os
import shutil
import subprocess
import sys


def main() -> None:
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )

    test_args = ["-m", "unittest", "discover", "-s", "tests", "-v"]

    if sys.platform == "win32":
        venv_python = os.path.join(project_dir, ".venv", "Scripts", "python.exe")
    else:
        venv_python = os.path.join(project_dir, ".venv", "bin", "python")

    if os.path.isfile(venv_python):
        cmd = [venv_python] + test_args
    elif shutil.which("nix"):
        cmd = ["nix", "develop", project_dir, "--command", "python3"] + test_args
    else:
        return

    result = subprocess.run(
        cmd,
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
