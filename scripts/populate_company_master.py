"""Batch-populate company_master.yaml with IRBank/EDINET metadata.

Reads input_full.csv, identifies codes missing from company_master.yaml,
fetches securities_report_pdf_url and address_source_urls from IRBank,
and merges results into the YAML.
"""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import yaml

from src.browser import BrowserService, BrowserServiceError
from src.company_config import load_company_master
from src.config import COMPANY_MASTER_PATH as _COMPANY_MASTER_PATH
from src.config import INPUT_FULL_CSV
from src.stealth import ProxyPool
from src.utils import validate_url_not_private

logger = logging.getLogger(__name__)

CompanyEntry = dict[str, str | list[str]]
CompanyMaster = dict[str, CompanyEntry]

COMPANY_MASTER_PATH = str(_COMPANY_MASTER_PATH)
INPUT_FULL_PATH = str(INPUT_FULL_CSV)

DEFAULT_TIMEOUT_MS = 30000
SAVE_INTERVAL = 100


def _atomic_save_company_master(path: str, data: CompanyMaster) -> None:
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


def _fetch_text(
    url: str,
    *,
    browser: BrowserService,
    pool: ProxyPool | None = None,
) -> str:
    validate_url_not_private(url)
    proxy_url: str | None = pool.get() if pool is not None else None
    resp = browser.fetch(url, proxy=proxy_url, timeout=DEFAULT_TIMEOUT_MS)
    if resp.html is None:
        raise BrowserServiceError(
            f"browser fetch failed for {url}: status={resp.status} error={resp.error}"
        )
    return resp.html


def fetch_metadata(
    code: str,
    *,
    browser: BrowserService,
    pool: ProxyPool | None = None,
) -> CompanyEntry | None:
    ir_url: str = f"https://irbank.net/{code}/ir"
    edinet_url: str = f"https://irbank.net/{code}/edinet"

    securities_report_pdf_url: str = ""
    ir_ok: bool = False

    with ThreadPoolExecutor(max_workers=2) as executor:
        ir_future = executor.submit(_fetch_text, ir_url, browser=browser, pool=pool)
        edinet_future = executor.submit(_fetch_text, edinet_url, browser=browser, pool=pool)

        try:
            ir_future.result()
            ir_ok = True
        except BrowserServiceError:
            logger.debug("IRBank IR page fetch failed: %s", ir_url, exc_info=True)

        try:
            html_edinet = edinet_future.result()
            doc_ids = re.findall(
                r'title="有価証券報告書[^"]*" href="notes\?f=(S100[0-9A-Z]+)"',
                html_edinet,
            )
            if not doc_ids:
                doc_ids = re.findall(
                    r'href="notes\?f=(S100[0-9A-Z]+)" title="有価証券報告書[^"]*"',
                    html_edinet,
                )
            if doc_ids:
                securities_report_pdf_url = (
                    f"https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/{doc_ids[0]}.pdf"
                )
        except BrowserServiceError:
            logger.debug("IRBank EDINET page fetch failed: %s", edinet_url, exc_info=True)

    if not ir_ok and not securities_report_pdf_url:
        return None

    entry: CompanyEntry = {}
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
    parser.add_argument("--workers", type=int, default=1, help="Number of concurrent workers (default: 1)")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay in seconds between requests (default: 1.0)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of codes to process (0=all)")
    parser.add_argument(
        "--proxy",
        default=None,
        help="Proxy URL (http://host:port, socks5://host:port). デフォルトは direct connection",
    )
    parser.add_argument(
        "--proxy-file",
        default=None,
        help="host:port:user:pass 形式のプロキシリストファイル",
    )
    args: argparse.Namespace = parser.parse_args()

    if args.proxy_file:
        pool: ProxyPool = ProxyPool.from_file(Path(args.proxy_file))
    elif args.proxy:
        pool = ProxyPool.from_url(args.proxy)
    else:
        pool = ProxyPool.make_direct()

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

    browser = BrowserService()
    browser.start()

    try:
        succeeded = 0
        failed_codes: list[str] = []
        lock = threading.Lock()
        processed = 0

        def process_code(code: str) -> tuple[str, CompanyEntry | None]:
            time.sleep(args.delay)
            try:
                return code, fetch_metadata(code, browser=browser, pool=pool)
            except BrowserServiceError as e:
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
    finally:
        browser.shutdown()


if __name__ == "__main__":
    main()
