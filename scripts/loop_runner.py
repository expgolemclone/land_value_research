"""land-value-run → split-address を無限ループで実行するスクリプト."""

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CMD_RUN = [
    "nix", "develop", "--command",
    "land-value-run", "--input", "config/input_full.csv", "--workers", "100",
]
WAIT_AFTER_RUN = 5 * 60  # 5 minutes

CMD_SPLIT = [
    "nix", "develop", "--command",
    "uv", "run", "python", "scripts/parallel_research.py", "split-address", "--n", "30",
]
WAIT_AFTER_SPLIT = 90 * 60  # 1 hour 30 minutes


def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


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
        log(f"waiting {WAIT_AFTER_RUN // 60} min ...")
        time.sleep(WAIT_AFTER_RUN)

        run(CMD_SPLIT, "split-address --n 30")
        log(f"waiting {WAIT_AFTER_SPLIT // 60} min ...")
        time.sleep(WAIT_AFTER_SPLIT)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("interrupted")
        sys.exit(0)
