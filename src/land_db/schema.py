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
    cache_version  INTEGER NOT NULL,
    pdf_size       INTEGER,
    pdf_mtime      REAL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS web_address_resolve (
    resolve_key TEXT PRIMARY KEY,
    address     TEXT NOT NULL,
    score       INTEGER NOT NULL,
    source_url  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invalidation_hashes (
    hash_type  TEXT NOT NULL,
    code       TEXT NOT NULL,
    hash_value TEXT NOT NULL,
    PRIMARY KEY (hash_type, code)
);
"""


def init_land_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_LAND_SCHEMA_SQL)
    conn.commit()
