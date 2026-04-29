"""Batch-populate land.db company metadata from IRBank/EDINET."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import logging
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.browser import BrowserService, BrowserServiceError
from src.company_store import connect_company_db, load_company_directory, merge_company_record
from src.config import INPUT_FULL_CSV
from src.stealth import ProxyPool
from src.stock_db_sync import sync_company_records_from_stock_db
from src.utils import validate_url_not_private

logger = logging.getLogger(__name__)

CompanyEntry = dict[str, str | list[str]]
INPUT_FULL_PATH = str(INPUT_FULL_CSV)

DEFAULT_TIMEOUT_MS = 30000
SAVE_INTERVAL = 100


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
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description="Populate land.db metadata from IRBank")
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
    conn = connect_company_db()
    master = load_company_directory(conn)

    synced = sync_company_records_from_stock_db(master, input_codes, conn=conn)
    if synced:
        conn.commit()
        print(f"stock.db 同期: {synced} 件のメタデータを補完")

    missing = [
        code
        for code in input_codes
        if not master.get(code, {}).get("securities_report_pdf_url")
        or not master.get(code, {}).get("address_source_urls")
    ]
    print(f"Total codes: {len(input_codes)}, Already stored: {len(master)}, Missing metadata: {len(missing)}")

    if not missing:
        print("Nothing to do.")
        conn.close()
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
            except BrowserServiceError as exc:
                print(f"  ERROR {code}: {exc}")
                return code, None

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(process_code, code): code for code in missing}

            for future in as_completed(futures):
                code, entry = future.result()
                with lock:
                    processed += 1
                    if entry:
                        succeeded += 1
                        if not args.dry_run:
                            master[code] = merge_company_record(
                                conn,
                                code,
                                securities_report_pdf_url=str(entry.get("securities_report_pdf_url", "")),
                                address_source_urls=list(entry.get("address_source_urls", []) or []),
                            )
                        else:
                            master[code] = dict(entry)
                    else:
                        failed_codes.append(code)

                    if processed % 50 == 0:
                        n_fail = len(failed_codes)
                        print(f"  Progress: {processed}/{len(missing)} (succeeded: {succeeded}, failed: {n_fail})")

                    if not args.dry_run and processed % SAVE_INTERVAL == 0:
                        conn.commit()
                        print(f"  Saved (interim) — {len(master)} entries")

        if not args.dry_run:
            conn.commit()
            print(f"Saved final — {len(master)} entries in land.db")
        else:
            print(f"[DRY RUN] Would have {len(master)} entries total")

        print(f"\nDone: {succeeded} succeeded, {len(failed_codes)} failed out of {len(missing)}")
        if failed_codes:
            print(f"Failed codes: {', '.join(sorted(failed_codes))}")
    finally:
        conn.close()
        browser.shutdown()


if __name__ == "__main__":
    main()
