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
    pdf_size       INTEGER,
    pdf_mtime      REAL,
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
"""


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()  # noqa: S608
    return {str(row[1]) for row in rows}


def _migrate(conn: sqlite3.Connection) -> None:
    facilities_cols = _table_columns(conn, "facilities_land")
    if facilities_cols and "section_text" not in facilities_cols:
        conn.execute("ALTER TABLE facilities_land ADD COLUMN section_text TEXT")
        conn.commit()

    resolve_cols = _table_columns(conn, "web_address_resolve")
    if resolve_cols and "resolved" not in resolve_cols:
        conn.execute("ALTER TABLE web_address_resolve ADD COLUMN resolved INTEGER NOT NULL DEFAULT 1")
        conn.commit()


def init_land_db(conn: sqlite3.Connection) -> None:
    _migrate(conn)
    conn.executescript(_LAND_SCHEMA_SQL)
    conn.commit()
