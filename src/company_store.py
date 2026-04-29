from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from stock_db.storage.connection import get_connection

from src.config import LAND_DB_PATH
from src.land_db.schema import init_land_db


class CompanyRecord(TypedDict, total=False):
    company_name: str
    securities_report_pdf_url: str
    address_source_urls: list[str]


CompanyDirectory = dict[str, CompanyRecord]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_company_db(db_path: Path | None = None) -> sqlite3.Connection:
    conn = get_connection(db_path or LAND_DB_PATH)
    init_db(conn)
    return conn


def connect_stocks_db(db_path: Path | None = None) -> sqlite3.Connection:
    return connect_company_db(db_path)


def init_db(conn: sqlite3.Connection) -> None:
    init_land_db(conn)


def _decode_urls(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if isinstance(loaded, list):
            return [str(x) for x in loaded if str(x).strip()]
    return []


def _merge_urls(current_urls: list[str], incoming_urls: list[str] | None) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for raw_url in [*current_urls, *(incoming_urls or [])]:
        url = str(raw_url).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        merged.append(url)
    return merged


def load_company_directory(conn: sqlite3.Connection) -> CompanyDirectory:
    rows = conn.execute(
        """
        SELECT code, company_name, securities_report_pdf_url, address_source_urls
        FROM company_metadata
        ORDER BY code
        """
    ).fetchall()
    result: CompanyDirectory = {}
    for row in rows:
        result[str(row["code"])] = CompanyRecord(
            company_name=str(row["company_name"] or ""),
            securities_report_pdf_url=str(row["securities_report_pdf_url"] or ""),
            address_source_urls=_decode_urls(row["address_source_urls"]),
        )
    return result


def load_company_record(conn: sqlite3.Connection, code: str) -> CompanyRecord:
    row = conn.execute(
        """
        SELECT code, company_name, securities_report_pdf_url, address_source_urls
        FROM company_metadata
        WHERE code = ?
        """,
        (code,),
    ).fetchone()
    if row is None:
        return CompanyRecord()
    return CompanyRecord(
        company_name=str(row["company_name"] or ""),
        securities_report_pdf_url=str(row["securities_report_pdf_url"] or ""),
        address_source_urls=_decode_urls(row["address_source_urls"]),
    )


def merge_company_record(
    conn: sqlite3.Connection,
    code: str,
    *,
    company_name: str | None = None,
    securities_report_pdf_url: str | None = None,
    address_source_urls: list[str] | None = None,
) -> CompanyRecord:
    current = load_company_record(conn, code)
    next_name = company_name if company_name is not None else current.get("company_name", "")
    next_pdf = (
        securities_report_pdf_url
        if securities_report_pdf_url is not None
        else current.get("securities_report_pdf_url", "")
    )
    next_urls = _merge_urls(list(current.get("address_source_urls", [])), address_source_urls)
    serialized_urls = json.dumps(next_urls, ensure_ascii=False) if next_urls else None

    conn.execute(
        """
        INSERT INTO company_metadata (
            code,
            company_name,
            securities_report_pdf_url,
            address_source_urls,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
            company_name = CASE
                WHEN excluded.company_name = '' THEN company_metadata.company_name
                ELSE excluded.company_name
            END,
            securities_report_pdf_url = CASE
                WHEN excluded.securities_report_pdf_url = '' THEN company_metadata.securities_report_pdf_url
                ELSE excluded.securities_report_pdf_url
            END,
            address_source_urls = COALESCE(excluded.address_source_urls, company_metadata.address_source_urls),
            updated_at = excluded.updated_at
        """,
        (code, str(next_name or ""), str(next_pdf or ""), serialized_urls, _now()),
    )
    return load_company_record(conn, code)


def load_company_name_map(conn: sqlite3.Connection) -> dict[str, str]:
    directory = load_company_directory(conn)
    return {code: str(entry.get("company_name", "")) for code, entry in directory.items()}


class MarketCapSnapshot(TypedDict):
    market_cap_yen: int
    fetched_date: str


def load_market_cap_snapshot(conn: sqlite3.Connection, code: str) -> MarketCapSnapshot | None:
    row = conn.execute(
        """
        SELECT market_cap_yen, fetched_date
        FROM market_cap_cache
        WHERE code = ?
        ORDER BY fetched_date DESC, updated_at DESC
        LIMIT 1
        """,
        (code,),
    ).fetchone()
    if row is None:
        return None
    return MarketCapSnapshot(
        market_cap_yen=int(row["market_cap_yen"]),
        fetched_date=str(row["fetched_date"]),
    )


def save_market_cap_snapshot(
    conn: sqlite3.Connection,
    code: str,
    market_cap_yen: int,
    fetched_date: str,
    *,
    source: str = "kabutan",
) -> None:
    conn.execute(
        """
        INSERT INTO market_cap_cache (
            code,
            source,
            market_cap_yen,
            fetched_date,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(code, source) DO UPDATE SET
            market_cap_yen = excluded.market_cap_yen,
            fetched_date = excluded.fetched_date,
            updated_at = excluded.updated_at
        """,
        (code, source, int(market_cap_yen), str(fetched_date), _now()),
    )
