"""Batch-populate land.db company metadata from IRBank/EDINET."""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.browser import BrowserService, BrowserServiceError
from src.company_metadata_fallback import fetch_from_irbank
from src.company_store import connect_company_db, load_company_directory, merge_company_record
from src.config import INPUT_FULL_CSV
from src.stock_db_sync import sync_company_records_from_stock_db

CompanyEntry = dict[str, str]
INPUT_FULL_PATH = str(INPUT_FULL_CSV)

SAVE_INTERVAL = 100


def fetch_metadata(
    code: str,
    *,
    browser: BrowserService,
) -> CompanyEntry | None:
    meta = fetch_from_irbank(code, browser=browser, need_name=True, need_pdf=True)
    if not meta.company_name and not meta.securities_report_pdf_url:
        return None

    entry: CompanyEntry = {}
    if meta.company_name:
        entry["company_name"] = meta.company_name
    if meta.securities_report_pdf_url:
        entry["securities_report_pdf_url"] = meta.securities_report_pdf_url
    return entry


def load_input_codes(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def _needs_company_name(entry: CompanyEntry, code: str) -> bool:
    company_name = str(entry.get("company_name", "") or "").strip()
    return not company_name or company_name == code


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description="Populate land.db metadata from IRBank")
    parser.add_argument("--workers", type=int, default=1, help="Number of concurrent workers (default: 1)")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay in seconds between requests (default: 1.0)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of codes to process (0=all)")
    args: argparse.Namespace = parser.parse_args()

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
        or _needs_company_name(master.get(code, {}), code)
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
                return code, fetch_metadata(code, browser=browser)
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
                                company_name=str(entry.get("company_name", "")),
                                securities_report_pdf_url=str(entry.get("securities_report_pdf_url", "")),
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
