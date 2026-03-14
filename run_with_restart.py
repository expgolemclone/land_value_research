"""Wrapper that auto-restarts run.py when it exits due to memory limit."""

import argparse
import subprocess
import sys
import time
from pathlib import Path

EXIT_CODE_MEMORY_LIMIT = 75
DEFAULT_MAX_RESTARTS = 10
RESTART_DELAY_SEC = 3


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="land-value-run-restart",
        description="run.py をメモリ制限終了時に自動再起動するラッパー",
        add_help=False,
    )
    parser.add_argument(
        "--max-restarts",
        type=int,
        default=DEFAULT_MAX_RESTARTS,
        help=f"最大再起動回数 (default: {DEFAULT_MAX_RESTARTS}, 0で無制限)",
    )
    known, run_py_args = parser.parse_known_args()

    run_py = str(Path(__file__).resolve().parent / "run.py")
    cmd = [sys.executable, run_py, *run_py_args]

    restart_count = 0
    while True:
        print(f"--- run.py 起動 (restart #{restart_count}) ---")
        result = subprocess.run(cmd)

        if result.returncode == 0:
            print("--- run.py 正常終了 ---")
            break

        if result.returncode == EXIT_CODE_MEMORY_LIMIT:
            restart_count += 1
            if known.max_restarts > 0 and restart_count >= known.max_restarts:
                print(f"--- 最大再起動回数 ({known.max_restarts}) に達しました。終了します ---")
                sys.exit(EXIT_CODE_MEMORY_LIMIT)
            print(f"--- メモリ制限により終了。{RESTART_DELAY_SEC}秒後に再起動します (#{restart_count}) ---")
            time.sleep(RESTART_DELAY_SEC)
            continue

        print(f"--- run.py がエラー終了しました (exit code: {result.returncode})。再起動しません ---")
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
