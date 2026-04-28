from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TypedDict

from stock_db.paths import STOCKS_DB_PATH
from stock_db.storage.connection import get_connection
from stock_db.storage.market_caps import get_market_cap, upsert_market_cap
from stock_db.storage.schema import init_db as init_stocks_db
from stock_db.storage.stocks import upsert_company_metadata, upsert_stock


class CompanyRecord(TypedDict, total=False):
    company_name: str
    securities_report_pdf_url: str
    address_source_urls: list[str]


CompanyDirectory = dict[str, CompanyRecord]


def connect_stocks_db(db_path: Path | None = None) -> sqlite3.Connection:
    conn = get_connection(db_path or STOCKS_DB_PATH)
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    init_stocks_db(conn)


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


def load_company_directory(conn: sqlite3.Connection) -> CompanyDirectory:
    rows = conn.execute(
        """
        SELECT ticker, name, securities_report_url, address_source_urls
        FROM stocks
        ORDER BY ticker
        """
    ).fetchall()
    result: CompanyDirectory = {}
    for row in rows:
        result[str(row["ticker"])] = CompanyRecord(
            company_name=str(row["name"] or ""),
            securities_report_pdf_url=str(row["securities_report_url"] or ""),
            address_source_urls=_decode_urls(row["address_source_urls"]),
        )
    return result


def load_company_record(conn: sqlite3.Connection, code: str) -> CompanyRecord:
    row = conn.execute(
        """
        SELECT ticker, name, securities_report_url, address_source_urls
        FROM stocks
        WHERE ticker = ?
        """,
        (code,),
    ).fetchone()
    if row is None:
        return CompanyRecord()
    return CompanyRecord(
        company_name=str(row["name"] or ""),
        securities_report_pdf_url=str(row["securities_report_url"] or ""),
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
    next_urls = address_source_urls if address_source_urls is not None else current.get("address_source_urls", [])

    upsert_stock(conn, code, str(next_name or ""), "", "")
    upsert_company_metadata(
        conn,
        code,
        securities_report_url=(str(next_pdf) if next_pdf else None),
        address_source_urls=(json.dumps(next_urls, ensure_ascii=False) if next_urls else None),
    )
    return load_company_record(conn, code)


def load_company_name_map(conn: sqlite3.Connection) -> dict[str, str]:
    directory = load_company_directory(conn)
    return {code: str(entry.get("company_name", "")) for code, entry in directory.items()}


class MarketCapSnapshot(TypedDict):
    market_cap_yen: int
    fetched_date: str


def load_market_cap_snapshot(conn: sqlite3.Connection, code: str) -> MarketCapSnapshot | None:
    row = get_market_cap(conn, code)
    if row is None:
        return None
    fetched_at = str(row["fetched_at"])
    return MarketCapSnapshot(
        market_cap_yen=int(row["value_yen"]),
        fetched_date=fetched_at[:10],
    )


def save_market_cap_snapshot(
    conn: sqlite3.Connection,
    code: str,
    market_cap_yen: int,
    fetched_date: str,
    *,
    source: str = "kabutan",
) -> None:
    upsert_market_cap(conn, code, source, int(market_cap_yen), str(fetched_date))
