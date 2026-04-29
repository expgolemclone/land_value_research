from __future__ import annotations

import logging
import re
import sqlite3
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from stock_db.paths import PROJECT_ROOT as STOCK_DB_PROJECT_ROOT
from stock_db.paths import STOCKS_DB_PATH
from stock_db.sources.edinet.api_client import build_pdf_url

from src.company_store import CompanyDirectory, merge_company_record

logger = logging.getLogger(__name__)

_SQLITE_BATCH_SIZE = 500
_WHITESPACE_RE = re.compile(r"\s+")
_DEFAULT_MARKET_CAP_MAX_AGE_DAYS = 7


@dataclass(frozen=True)
class StockDbCompanyMetadata:
    company_name: str = ""
    securities_report_pdf_url: str = ""


def _normalize_codes(codes: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_code in codes:
        code = str(raw_code).strip()
        if not code or code in seen:
            continue
        seen.add(code)
        normalized.append(code)
    return normalized


def _code_batches(codes: list[str], size: int = _SQLITE_BATCH_SIZE) -> list[list[str]]:
    return [codes[i : i + size] for i in range(0, len(codes), size)]


def _open_stock_db_readonly(db_path: Path) -> sqlite3.Connection | None:
    resolved = db_path.expanduser().resolve()
    if not resolved.exists():
        logger.info("stock.db が見つからないため同期をスキップ: %s", resolved)
        return None
    try:
        conn = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    except sqlite3.Error:
        logger.exception("stock.db を read-only で開けませんでした: %s", resolved)
        return None
    conn.row_factory = sqlite3.Row
    return conn


def _is_placeholder_company_name(company_name: str, code: str) -> bool:
    compact_name = _WHITESPACE_RE.sub("", company_name or "")
    return not compact_name or compact_name == code


def load_stock_db_company_metadata(
    codes: Iterable[str],
    *,
    db_path: Path | None = None,
) -> dict[str, StockDbCompanyMetadata]:
    normalized_codes = _normalize_codes(codes)
    if not normalized_codes:
        return {}

    conn = _open_stock_db_readonly(db_path or STOCKS_DB_PATH)
    if conn is None:
        return {}

    result: dict[str, StockDbCompanyMetadata] = {}
    try:
        for batch in _code_batches(normalized_codes):
            placeholders = ",".join("?" for _ in batch)
            stock_rows = conn.execute(
                f"""
                SELECT ticker, name, securities_report_url
                FROM stocks
                WHERE ticker IN ({placeholders})
                """,
                batch,
            ).fetchall()
            sec_report_rows = conn.execute(
                f"""
                SELECT ticker, doc_id
                FROM sec_reports
                WHERE ticker IN ({placeholders})
                  AND COALESCE(doc_id, '') <> ''
                ORDER BY
                    ticker,
                    CASE WHEN fiscal_year = 'latest' THEN 0 ELSE 1 END,
                    updated_at DESC,
                    doc_id DESC
                """,
                batch,
            ).fetchall()

            doc_id_by_ticker: dict[str, str] = {}
            for row in sec_report_rows:
                ticker = str(row["ticker"])
                if ticker not in doc_id_by_ticker:
                    doc_id_by_ticker[ticker] = str(row["doc_id"])

            for row in stock_rows:
                ticker = str(row["ticker"])
                pdf_url = str(row["securities_report_url"] or "")
                if not pdf_url:
                    doc_id = doc_id_by_ticker.get(ticker, "")
                    if doc_id:
                        pdf_url = build_pdf_url(doc_id)
                metadata = StockDbCompanyMetadata(
                    company_name=str(row["name"] or ""),
                    securities_report_pdf_url=pdf_url,
                )
                if metadata.company_name or metadata.securities_report_pdf_url:
                    result[ticker] = metadata

            for ticker, doc_id in doc_id_by_ticker.items():
                if ticker not in result:
                    result[ticker] = StockDbCompanyMetadata(
                        securities_report_pdf_url=build_pdf_url(doc_id),
                    )
    finally:
        conn.close()

    return result


def load_market_cap_from_stock_db(
    codes: Iterable[str],
    *,
    db_path: Path | None = None,
    max_age_days: int = _DEFAULT_MARKET_CAP_MAX_AGE_DAYS,
) -> dict[str, int]:
    normalized_codes = _normalize_codes(codes)
    if not normalized_codes:
        return {}
    if max_age_days < 0:
        raise ValueError("max_age_days must be >= 0")

    conn = _open_stock_db_readonly(db_path or STOCKS_DB_PATH)
    if conn is None:
        return {}

    cutoff_date = date.today() - timedelta(days=max_age_days)
    result: dict[str, int] = {}
    try:
        for batch in _code_batches(normalized_codes):
            placeholders = ",".join("?" for _ in batch)
            rows = conn.execute(
                f"""
                WITH latest_prices AS (
                    SELECT
                        ticker,
                        date,
                        close,
                        ROW_NUMBER() OVER (
                            PARTITION BY ticker
                            ORDER BY date DESC
                        ) AS rn
                    FROM prices
                    WHERE ticker IN ({placeholders})
                )
                SELECT
                    s.ticker,
                    s.shares_outstanding,
                    lp.close,
                    lp.date
                FROM stocks AS s
                JOIN latest_prices AS lp
                  ON lp.ticker = s.ticker
                 AND lp.rn = 1
                WHERE s.shares_outstanding IS NOT NULL
                  AND lp.close IS NOT NULL
                """,
                batch,
            ).fetchall()

            for row in rows:
                price_date_raw = str(row["date"] or "")
                try:
                    price_date = date.fromisoformat(price_date_raw)
                except ValueError:
                    logger.debug("stock.db price date parse failed: ticker=%s date=%r", row["ticker"], price_date_raw)
                    continue
                if price_date < cutoff_date:
                    continue

                shares_outstanding = int(row["shares_outstanding"])
                close = float(row["close"])
                result[str(row["ticker"])] = int(round(shares_outstanding * close))
    finally:
        conn.close()

    return result


def run_stooq_scrape(
    *,
    cwd: Path | None = None,
    timeout: int = 300,
) -> bool:
    """stock_db で scrape-stooq-prices を実行して最新株価を取得する."""
    work_dir = cwd or STOCK_DB_PROJECT_ROOT
    logger.info("stooq 株価スクレイプ開始: cwd=%s", work_dir)
    try:
        proc = subprocess.run(
            ["uv", "run", "scrape-stooq-prices"],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.warning("stooq 株価スクレイプ失敗: %s: %s", type(exc).__name__, exc)
        return False

    if proc.returncode != 0:
        logger.warning(
            "stooq 株価スクレイプ失敗 (exit=%d): %s",
            proc.returncode,
            (proc.stderr or "").strip(),
        )
        return False

    logger.info("stooq 株価スクレイプ完了: %s", (proc.stderr or "").strip())
    return True


def sync_company_records_from_stock_db(
    company_records: CompanyDirectory,
    codes: Iterable[str],
    *,
    conn: sqlite3.Connection | None = None,
    db_path: Path | None = None,
) -> int:
    metadata_by_code = load_stock_db_company_metadata(codes, db_path=db_path)
    updated = 0

    for code, metadata in metadata_by_code.items():
        current = company_records.get(code, {})
        next_values: dict[str, str] = {}

        current_name = str(current.get("company_name", "") or "")
        if metadata.company_name and _is_placeholder_company_name(current_name, code):
            next_values["company_name"] = metadata.company_name

        current_pdf_url = str(current.get("securities_report_pdf_url", "") or "")
        if metadata.securities_report_pdf_url and not current_pdf_url:
            next_values["securities_report_pdf_url"] = metadata.securities_report_pdf_url

        if not next_values:
            continue

        if conn is not None:
            company_records[code] = merge_company_record(conn, code, **next_values)
        else:
            merged = dict(current)
            merged.update(next_values)
            company_records[code] = merged
        updated += 1

    return updated
