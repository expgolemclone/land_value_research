"""Batch-populate company_master.yaml with IRBank/EDINET metadata.

Reads input_full.csv, identifies codes missing from company_master.yaml,
fetches securities_report_pdf_url and address_source_urls from IRBank,
and merges results into the YAML.
"""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import yaml

from src.company_config import load_company_master
from src.network import urlopen_with_retry
from src.config import COMPANY_MASTER_PATH as _COMPANY_MASTER_PATH
from src.config import INPUT_FULL_CSV
from src.stealth import ProxyPool
from src.utils import validate_url_not_private

COMPANY_MASTER_PATH = str(_COMPANY_MASTER_PATH)
INPUT_FULL_PATH = str(INPUT_FULL_CSV)

DEFAULT_TIMEOUT_SEC = 20
SAVE_INTERVAL = 100


def _atomic_save_company_master(path: str, data: dict[str, dict[str, Any]]) -> None:
    """Write company_master.yaml atomically via temp file + rename."""
    sorted_data = dict(sorted(data.items(), key=lambda x: x[0]))
    dir_path = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(suffix=".yaml", dir=dir_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(sorted_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        os.replace(tmp_path, path)
    except BaseException:
        os.unlink(tmp_path)
        raise


def _fetch_text(url: str, *, pool: ProxyPool | None = None) -> str:
    validate_url_not_private(url)
    req: urllib.request.Request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; land_value_research/1.0)"},
    )
    body: bytes = urlopen_with_retry(req, timeout_sec=DEFAULT_TIMEOUT_SEC, pool=pool)
    return body.decode("utf-8", errors="ignore")


def fetch_metadata(
    code: str,
    *,
    pool: ProxyPool | None = None,
) -> dict[str, str | list[str]] | None:
    """Fetch EDINET PDF URL and IR page URL for a single company code."""
    ir_url: str = f"https://irbank.net/{code}/ir"
    edinet_url: str = f"https://irbank.net/{code}/edinet"

    securities_report_pdf_url: str = ""
    ir_ok: bool = False

    with ThreadPoolExecutor(max_workers=2) as executor:
        ir_future = executor.submit(_fetch_text, ir_url, pool=pool)
        edinet_future = executor.submit(_fetch_text, edinet_url, pool=pool)

        try:
            ir_future.result()
            ir_ok = True
        except Exception:
            pass

        try:
            html_edinet = edinet_future.result()
            doc_ids = re.findall(
                r'title="有価証券報告書[^"]*" href="notes\?f=(S100[0-9A-Z]+)"',
                html_edinet,
            )
            if doc_ids:
                securities_report_pdf_url = (
                    f"https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/{doc_ids[0]}.pdf"
                )
        except Exception:
            pass

    if not ir_ok and not securities_report_pdf_url:
        return None

    entry: dict[str, str | list[str]] = {}
    if securities_report_pdf_url:
        entry["securities_report_pdf_url"] = securities_report_pdf_url
    if ir_ok:
        entry["address_source_urls"] = [ir_url]
    return entry


def load_input_codes(path: str) -> list[str]:
    codes = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            code = line.strip()
            if code:
                codes.append(code)
    return codes


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description="Populate company_master.yaml from IRBank")
    parser.add_argument("--workers", type=int, default=4, help="Number of concurrent workers (default: 4)")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay in seconds between requests (default: 0.3)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of codes to process (0=all)")
    parser.add_argument("--proxy", default=None, help="HTTP proxy URL (e.g. http://host:port)")
    parser.add_argument("--no-proxy", action="store_true", default=False, help="Disable auto-proxy")
    args: argparse.Namespace = parser.parse_args()

    if args.proxy:
        pool: ProxyPool = ProxyPool.from_url(args.proxy)
    elif args.no_proxy:
        pool = ProxyPool.direct()
    else:
        pool = ProxyPool.from_auto()

    input_codes = load_input_codes(INPUT_FULL_PATH)
    master = load_company_master(COMPANY_MASTER_PATH)

    missing = [c for c in input_codes if c not in master]
    print(f"Total codes: {len(input_codes)}, Already in master: {len(master)}, Missing: {len(missing)}")

    if not missing:
        print("Nothing to do.")
        return

    if args.limit > 0:
        missing = missing[: args.limit]
        print(f"Limited to {len(missing)} codes")

    succeeded = 0
    failed_codes: list[str] = []
    lock = threading.Lock()
    processed = 0

    def process_code(code: str) -> tuple[str, dict[str, str | list[str]] | None]:
        time.sleep(args.delay)
        try:
            return code, fetch_metadata(code, pool=pool)
        except Exception as e:
            print(f"  ERROR {code}: {e}")
            return code, None

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_code, code): code for code in missing}

        for future in as_completed(futures):
            code, entry = future.result()
            with lock:
                processed += 1
                if entry:
                    succeeded += 1
                    master[code] = entry
                else:
                    failed_codes.append(code)

                if processed % 50 == 0:
                    n_fail = len(failed_codes)
                    print(f"  Progress: {processed}/{len(missing)} (succeeded: {succeeded}, failed: {n_fail})")

                if not args.dry_run and processed % SAVE_INTERVAL == 0:
                    _atomic_save_company_master(COMPANY_MASTER_PATH, master)
                    print(f"  Saved (interim) — {len(master)} entries")

    if not args.dry_run:
        _atomic_save_company_master(COMPANY_MASTER_PATH, master)
        print(f"Saved final — {len(master)} entries in company_master.yaml")
    else:
        print(f"[DRY RUN] Would have {len(master)} entries total")

    print(f"\nDone: {succeeded} succeeded, {len(failed_codes)} failed out of {len(missing)}")
    if failed_codes:
        print(f"Failed codes: {', '.join(sorted(failed_codes))}")


if __name__ == "__main__":
    main()
