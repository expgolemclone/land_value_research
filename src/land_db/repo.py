from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import TypedDict


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# TypedDicts for structured data
# ---------------------------------------------------------------------------


class LandPriceResult(TypedDict, total=False):
    unit_price: int
    nearest_id: str
    nearest_dist_m: float
    knn_ids: list[str]
    knn_dist_m: list[float]
    knn_prices: list[int]
    landuse_kind: str


class SiteEntry(TypedDict, total=False):
    site_name: str
    location_short: str
    land_area_m2: float
    land_book_value_yen: float
    location_has_hoka: bool
    equipment_type: str


class ResolveEntry(TypedDict):
    address: str
    score: int
    source_url: str


class ResolveCacheRecord(TypedDict, total=False):
    resolved: bool
    address: str
    score: int
    source_url: str


# ---------------------------------------------------------------------------
# land_price_cache
# ---------------------------------------------------------------------------


def save_land_price_cache(
    conn: sqlite3.Connection,
    cache_key: str,
    result: LandPriceResult,
) -> None:
    conn.execute(
        """
        INSERT INTO land_price_cache (cache_key, result_json)
        VALUES (?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET result_json = excluded.result_json
        """,
        (cache_key, json.dumps(result, ensure_ascii=False)),
    )


def load_land_price_cache(
    conn: sqlite3.Connection,
    cache_key: str,
) -> LandPriceResult | None:
    row = conn.execute(
        "SELECT result_json FROM land_price_cache WHERE cache_key = ?",
        (cache_key,),
    ).fetchone()
    if row is None:
        return None
    return json.loads(row[0])


def get_land_price_deps_hash(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT value FROM land_price_meta WHERE key = 'deps_hash'",
    ).fetchone()
    return row[0] if row else None


def set_land_price_deps_hash(conn: sqlite3.Connection, hash_value: str) -> None:
    conn.execute(
        """
        INSERT INTO land_price_meta (key, value) VALUES ('deps_hash', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (hash_value,),
    )


# ---------------------------------------------------------------------------
# geocode_cache
# ---------------------------------------------------------------------------


def save_geocode_cache(
    conn: sqlite3.Connection,
    address: str,
    lat: float,
    lon: float,
    level: str,
) -> None:
    conn.execute(
        """
        INSERT INTO geocode_cache (address, lat, lon, level)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(address) DO UPDATE SET
            lat = excluded.lat, lon = excluded.lon, level = excluded.level
        """,
        (address, lat, lon, level),
    )


def load_geocode_cache(
    conn: sqlite3.Connection,
    address: str,
) -> tuple[float, float, str] | None:
    row = conn.execute(
        "SELECT lat, lon, level FROM geocode_cache WHERE address = ?",
        (address,),
    ).fetchone()
    if row is None:
        return None
    return (row[0], row[1], row[2])


def get_geocode_deps_hash(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT value FROM geocode_meta WHERE key = 'deps_hash'",
    ).fetchone()
    return row[0] if row else None


def set_geocode_deps_hash(conn: sqlite3.Connection, hash_value: str) -> None:
    conn.execute(
        """
        INSERT INTO geocode_meta (key, value) VALUES ('deps_hash', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (hash_value,),
    )


# ---------------------------------------------------------------------------
# facilities_land
# ---------------------------------------------------------------------------


def save_sites_cache(
    conn: sqlite3.Connection,
    code: str,
    sites: list[SiteEntry],
    *,
    cache_version: int,
    pdf_size: int,
    pdf_mtime: float,
    section_text: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO facilities_land (code, sites_json, section_text, cache_version, pdf_size, pdf_mtime, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
            sites_json    = excluded.sites_json,
            section_text  = COALESCE(excluded.section_text, facilities_land.section_text),
            cache_version = excluded.cache_version,
            pdf_size      = excluded.pdf_size,
            pdf_mtime     = excluded.pdf_mtime,
            updated_at    = excluded.updated_at
        """,
        (code, json.dumps(sites, ensure_ascii=False), section_text, cache_version, pdf_size, pdf_mtime, _now()),
    )


def load_sites_cache(
    conn: sqlite3.Connection,
    code: str,
    *,
    pdf_size: int,
    pdf_mtime: float,
) -> list[SiteEntry] | None:
    row = conn.execute(
        "SELECT sites_json, pdf_size, pdf_mtime FROM facilities_land WHERE code = ?",
        (code,),
    ).fetchone()
    if row is None:
        return None
    if int(row["pdf_size"]) != pdf_size or float(row["pdf_mtime"]) != pdf_mtime:
        return None
    return json.loads(row["sites_json"])


def save_facilities_section_text(
    conn: sqlite3.Connection,
    code: str,
    section_text: str,
    *,
    cache_version: int,
    pdf_size: int,
    pdf_mtime: float,
) -> None:
    conn.execute(
        """
        INSERT INTO facilities_land (code, sites_json, section_text, cache_version, pdf_size, pdf_mtime, updated_at)
        VALUES (?, '[]', ?, ?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
            section_text  = excluded.section_text,
            cache_version = excluded.cache_version,
            pdf_size      = excluded.pdf_size,
            pdf_mtime     = excluded.pdf_mtime,
            updated_at    = excluded.updated_at
        """,
        (code, section_text, cache_version, pdf_size, pdf_mtime, _now()),
    )


def load_facilities_section_text(
    conn: sqlite3.Connection,
    code: str,
    *,
    pdf_size: int,
    pdf_mtime: float,
) -> str | None:
    row = conn.execute(
        "SELECT section_text, pdf_size, pdf_mtime FROM facilities_land WHERE code = ?",
        (code,),
    ).fetchone()
    if row is None:
        return None
    if int(row["pdf_size"]) != pdf_size or float(row["pdf_mtime"]) != pdf_mtime:
        return None
    section_text = row["section_text"]
    return str(section_text) if section_text is not None else None


def load_facilities_cache(
    conn: sqlite3.Connection,
    code: str,
    *,
    pdf_size: int,
    pdf_mtime: float,
) -> tuple[list[SiteEntry], str | None] | None:
    row = conn.execute(
        "SELECT sites_json, section_text, pdf_size, pdf_mtime FROM facilities_land WHERE code = ?",
        (code,),
    ).fetchone()
    if row is None:
        return None
    if int(row["pdf_size"]) != pdf_size or float(row["pdf_mtime"]) != pdf_mtime:
        return None
    section_text = row["section_text"]
    return (json.loads(row["sites_json"]), str(section_text) if section_text is not None else None)


# ---------------------------------------------------------------------------
# web_address_resolve
# ---------------------------------------------------------------------------


def save_resolve_cache(
    conn: sqlite3.Connection,
    resolve_key: str,
    entry: ResolveEntry,
) -> None:
    save_resolve_cache_record(
        conn,
        resolve_key,
        ResolveCacheRecord(
            resolved=True,
            address=entry["address"],
            score=entry["score"],
            source_url=entry["source_url"],
        ),
    )


def save_resolve_miss(conn: sqlite3.Connection, resolve_key: str) -> None:
    save_resolve_cache_record(conn, resolve_key, ResolveCacheRecord(resolved=False))


def save_resolve_cache_record(
    conn: sqlite3.Connection,
    resolve_key: str,
    entry: ResolveCacheRecord,
) -> None:
    resolved = bool(entry.get("resolved", True))
    conn.execute(
        """
        INSERT INTO web_address_resolve (resolve_key, resolved, address, score, source_url)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(resolve_key) DO UPDATE SET
            resolved   = excluded.resolved,
            address    = excluded.address,
            score      = excluded.score,
            source_url = excluded.source_url
        """,
        (
            resolve_key,
            1 if resolved else 0,
            entry.get("address"),
            entry.get("score"),
            entry.get("source_url"),
        ),
    )


def load_resolve_cache(
    conn: sqlite3.Connection,
    resolve_key: str,
) -> ResolveEntry | None:
    row = load_resolve_cache_record(conn, resolve_key)
    if row is None or not row["resolved"]:
        return None
    return ResolveEntry(address=row["address"], score=row["score"], source_url=row["source_url"])


def load_resolve_cache_record(
    conn: sqlite3.Connection,
    resolve_key: str,
) -> ResolveCacheRecord | None:
    row = conn.execute(
        "SELECT resolved, address, score, source_url FROM web_address_resolve WHERE resolve_key = ?",
        (resolve_key,),
    ).fetchone()
    if row is None:
        return None
    record = ResolveCacheRecord(resolved=bool(row["resolved"]))
    if record["resolved"]:
        record["address"] = str(row["address"])
        record["score"] = int(row["score"])
        record["source_url"] = str(row["source_url"])
    return record


# ---------------------------------------------------------------------------
# invalidation_hashes
# ---------------------------------------------------------------------------


def save_invalidation_hash(
    conn: sqlite3.Connection,
    hash_type: str,
    code: str,
    hash_value: str,
) -> None:
    conn.execute(
        """
        INSERT INTO invalidation_hashes (hash_type, code, hash_value)
        VALUES (?, ?, ?)
        ON CONFLICT(hash_type, code) DO UPDATE SET hash_value = excluded.hash_value
        """,
        (hash_type, code, hash_value),
    )


def load_invalidation_hash(
    conn: sqlite3.Connection,
    hash_type: str,
    code: str,
) -> str | None:
    row = conn.execute(
        "SELECT hash_value FROM invalidation_hashes WHERE hash_type = ? AND code = ?",
        (hash_type, code),
    ).fetchone()
    return row[0] if row else None


def list_invalidation_hashes(
    conn: sqlite3.Connection,
    hash_type: str,
) -> dict[str, str]:
    rows = conn.execute(
        "SELECT code, hash_value FROM invalidation_hashes WHERE hash_type = ?",
        (hash_type,),
    ).fetchall()
    return {str(row["code"]): str(row["hash_value"]) for row in rows}


def delete_invalidation_hash(
    conn: sqlite3.Connection,
    hash_type: str,
    code: str,
) -> None:
    conn.execute(
        "DELETE FROM invalidation_hashes WHERE hash_type = ? AND code = ?",
        (hash_type, code),
    )
