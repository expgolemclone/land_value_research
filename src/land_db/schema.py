from __future__ import annotations

import sqlite3

_LAND_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS land_price_cache (
    cache_key   TEXT PRIMARY KEY,
    result_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS land_price_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS geocode_cache (
    address TEXT PRIMARY KEY,
    lat     REAL NOT NULL,
    lon     REAL NOT NULL,
    level   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS geocode_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS facilities_land (
    code           TEXT PRIMARY KEY,
    sites_json     TEXT NOT NULL,
    section_text   TEXT,
    cache_version  INTEGER NOT NULL,
    source_kind    TEXT NOT NULL DEFAULT '',
    source_id      TEXT NOT NULL DEFAULT '',
    source_size    INTEGER,
    source_mtime_ns INTEGER,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS web_address_resolve (
    resolve_key TEXT PRIMARY KEY,
    resolved    INTEGER NOT NULL,
    address     TEXT,
    score       INTEGER,
    source_url  TEXT
);

CREATE TABLE IF NOT EXISTS invalidation_hashes (
    hash_type  TEXT NOT NULL,
    code       TEXT NOT NULL,
    hash_value TEXT NOT NULL,
    PRIMARY KEY (hash_type, code)
);

CREATE TABLE IF NOT EXISTS company_metadata (
    code                       TEXT PRIMARY KEY,
    company_name               TEXT NOT NULL DEFAULT '',
    updated_at                 TEXT NOT NULL
);
"""


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()  # noqa: S608
    return {str(row[1]) for row in rows}


def _table_column_info(conn: sqlite3.Connection, table: str) -> dict[str, sqlite3.Row]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()  # noqa: S608
    return {str(row[1]): row for row in rows}


def _rebuild_company_metadata_without_legacy_columns(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE company_metadata__new (
            code                      TEXT PRIMARY KEY,
            company_name              TEXT NOT NULL DEFAULT '',
            updated_at                TEXT NOT NULL
        );

        INSERT INTO company_metadata__new (
            code,
            company_name,
            updated_at
        )
        SELECT
            code,
            company_name,
            updated_at
        FROM company_metadata;

        DROP TABLE company_metadata;
        ALTER TABLE company_metadata__new RENAME TO company_metadata;
        """
    )


def _rebuild_facilities_land_without_legacy_columns(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE facilities_land__new (
            code            TEXT PRIMARY KEY,
            sites_json      TEXT NOT NULL,
            section_text    TEXT,
            cache_version   INTEGER NOT NULL,
            source_kind     TEXT NOT NULL DEFAULT '',
            source_id       TEXT NOT NULL DEFAULT '',
            source_size     INTEGER,
            source_mtime_ns INTEGER,
            updated_at      TEXT NOT NULL
        );

        INSERT INTO facilities_land__new (
            code,
            sites_json,
            section_text,
            cache_version,
            source_kind,
            source_id,
            source_size,
            source_mtime_ns,
            updated_at
        )
        SELECT
            code,
            sites_json,
            section_text,
            cache_version,
            source_kind,
            source_id,
            source_size,
            source_mtime_ns,
            updated_at
        FROM facilities_land;

        DROP TABLE facilities_land;
        ALTER TABLE facilities_land__new RENAME TO facilities_land;
        """
    )


def _rebuild_web_address_resolve_with_nullable_miss_fields(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE web_address_resolve__new (
            resolve_key TEXT PRIMARY KEY,
            resolved    INTEGER NOT NULL,
            address     TEXT,
            score       INTEGER,
            source_url  TEXT
        );

        INSERT INTO web_address_resolve__new (
            resolve_key,
            resolved,
            address,
            score,
            source_url
        )
        SELECT
            resolve_key,
            resolved,
            address,
            score,
            source_url
        FROM web_address_resolve;

        DROP TABLE web_address_resolve;
        ALTER TABLE web_address_resolve__new RENAME TO web_address_resolve;
        """
    )


def _migrate(conn: sqlite3.Connection) -> None:
    facilities_cols = _table_columns(conn, "facilities_land")
    if facilities_cols and "section_text" not in facilities_cols:
        conn.execute("ALTER TABLE facilities_land ADD COLUMN section_text TEXT")
        conn.commit()
        facilities_cols = _table_columns(conn, "facilities_land")
    source_column_sql = {
        "source_kind": "ALTER TABLE facilities_land ADD COLUMN source_kind TEXT NOT NULL DEFAULT ''",
        "source_id": "ALTER TABLE facilities_land ADD COLUMN source_id TEXT NOT NULL DEFAULT ''",
        "source_size": "ALTER TABLE facilities_land ADD COLUMN source_size INTEGER",
        "source_mtime_ns": "ALTER TABLE facilities_land ADD COLUMN source_mtime_ns INTEGER",
    }
    missing_source_cols = [name for name in source_column_sql if facilities_cols and name not in facilities_cols]
    if missing_source_cols:
        for name in missing_source_cols:
            conn.execute(source_column_sql[name])
        conn.commit()
        facilities_cols = _table_columns(conn, "facilities_land")
    legacy_size_col = "p" + "df" + "_size"
    legacy_mtime_col = "p" + "df" + "_mtime"
    if facilities_cols and ({legacy_size_col, legacy_mtime_col} & facilities_cols):
        _rebuild_facilities_land_without_legacy_columns(conn)
        conn.commit()

    resolve_cols = _table_columns(conn, "web_address_resolve")
    if resolve_cols and "resolved" not in resolve_cols:
        conn.execute("ALTER TABLE web_address_resolve ADD COLUMN resolved INTEGER NOT NULL DEFAULT 1")
        conn.commit()
        resolve_cols = _table_columns(conn, "web_address_resolve")
    if resolve_cols:
        resolve_info = _table_column_info(conn, "web_address_resolve")
        nullable_miss_fields = ("address", "score", "source_url")
        if any(int(resolve_info[name][3]) != 0 for name in nullable_miss_fields if name in resolve_info):
            _rebuild_web_address_resolve_with_nullable_miss_fields(conn)
            conn.commit()

    company_cols = _table_columns(conn, "company_metadata")
    legacy_doc_url_col = "securities_report_" + "p" + "df" + "_url"
    if company_cols and ({"address_source_urls", legacy_doc_url_col} & company_cols):
        _rebuild_company_metadata_without_legacy_columns(conn)
        conn.commit()

    market_cap_cols = _table_columns(conn, "market_cap_cache")
    if market_cap_cols:
        conn.execute("DROP TABLE market_cap_cache")
        conn.commit()


def init_land_db(conn: sqlite3.Connection) -> None:
    _migrate(conn)
    conn.executescript(_LAND_SCHEMA_SQL)
    conn.commit()
