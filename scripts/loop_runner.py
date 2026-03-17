"""land-value-run → split-address を無限ループで実行するスクリプト."""

import select
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CMD_RUN = [
    "nix",
    "develop",
    "--command",
    "land-value-run",
    "--input",
    "config/input_full.csv",
    "--workers",
    "100",
]
WAIT_AFTER_RUN = 5 * 60  # 5 minutes

CMD_SPLIT = [
    "nix",
    "develop",
    "--command",
    "uv",
    "run",
    "python",
    "scripts/parallel_research.py",
    "split-address",
    "--n",
    "30",
]
WAIT_AFTER_SPLIT = 90 * 60  # 1 hour 30 minutes


SKIP_ENTER_COUNT = 3


def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def wait_with_skip(seconds: int) -> None:
    """Wait for `seconds`, but skip if Enter is pressed SKIP_ENTER_COUNT times."""
    enter_count = 0
    remaining = seconds
    while remaining > 0:
        ready, _, _ = select.select([sys.stdin], [], [], 1.0)
        if ready:
            sys.stdin.readline()
            enter_count += 1
            if enter_count >= SKIP_ENTER_COUNT:
                log("skip!")
                return
            log(f"Enter {enter_count}/{SKIP_ENTER_COUNT} to skip")
        remaining -= 1


def run(cmd: list[str], label: str) -> None:
    log(f"START: {label}")
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    log(f"END:   {label} (exit={result.returncode})")


def main() -> None:
    iteration = 0
    while True:
        iteration += 1
        log(f"===== iteration {iteration} =====")

        run(CMD_RUN, "land-value-run")
        log(f"waiting {WAIT_AFTER_RUN // 60} min ... (Enter x{SKIP_ENTER_COUNT} to skip)")
        wait_with_skip(WAIT_AFTER_RUN)

        run(CMD_SPLIT, "split-address --n 30")
        log(f"waiting {WAIT_AFTER_SPLIT // 60} min ... (Enter x{SKIP_ENTER_COUNT} to skip)")
        wait_with_skip(WAIT_AFTER_SPLIT)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("interrupted")
        sys.exit(0)
