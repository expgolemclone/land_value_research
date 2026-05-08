from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from stock_db.storage.connection import get_connection

from src.config import LAND_DB_PATH
from src.land_db.asset import ensure_land_db_exists
from src.land_db.schema import init_land_db


class CompanyRecord(TypedDict, total=False):
    company_name: str
    securities_report_pdf_url: str


CompanyDirectory = dict[str, CompanyRecord]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def connect_company_db(db_path: Path | None = None) -> sqlite3.Connection:
    resolved_path = db_path or LAND_DB_PATH
    if db_path is None:
        ensure_land_db_exists(resolved_path)
    conn = get_connection(resolved_path)
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    init_land_db(conn)


def load_company_directory(conn: sqlite3.Connection) -> CompanyDirectory:
    rows = conn.execute(
        """
        SELECT code, company_name, securities_report_pdf_url
        FROM company_metadata
        ORDER BY code
        """
    ).fetchall()
    result: CompanyDirectory = {}
    for row in rows:
        result[str(row["code"])] = CompanyRecord(
            company_name=str(row["company_name"] or ""),
            securities_report_pdf_url=str(row["securities_report_pdf_url"] or ""),
        )
    return result


def load_company_record(conn: sqlite3.Connection, code: str) -> CompanyRecord:
    row = conn.execute(
        """
        SELECT code, company_name, securities_report_pdf_url
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
    )


def merge_company_record(
    conn: sqlite3.Connection,
    code: str,
    *,
    company_name: str | None = None,
    securities_report_pdf_url: str | None = None,
) -> CompanyRecord:
    current = load_company_record(conn, code)
    next_name = company_name if company_name is not None else current.get("company_name", "")
    next_pdf = (
        securities_report_pdf_url
        if securities_report_pdf_url is not None
        else current.get("securities_report_pdf_url", "")
    )

    conn.execute(
        """
        INSERT INTO company_metadata (
            code,
            company_name,
            securities_report_pdf_url,
            updated_at
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
            company_name = CASE
                WHEN excluded.company_name = '' THEN company_metadata.company_name
                ELSE excluded.company_name
            END,
            securities_report_pdf_url = CASE
                WHEN excluded.securities_report_pdf_url = '' THEN company_metadata.securities_report_pdf_url
                ELSE excluded.securities_report_pdf_url
            END,
            updated_at = excluded.updated_at
        """,
        (code, str(next_name or ""), str(next_pdf or ""), _now()),
    )
    return load_company_record(conn, code)


def load_company_name_map(conn: sqlite3.Connection) -> dict[str, str]:
    directory = load_company_directory(conn)
    return {code: str(entry.get("company_name", "")) for code, entry in directory.items()}
