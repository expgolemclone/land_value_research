#!/usr/bin/env python3
"""Migrate legacy cache artifacts into land.db and stocks.db."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from stock_db.paths import STOCKS_DB_PATH
from stock_db.storage.connection import get_connection

from src.company_store import init_db as init_stocks_db
from src.config import CACHE_DIR, LAND_DB_PATH, WEB_ADDRESS_CACHE_DIR
from src.land_db.repo import (
    save_geocode_cache,
    save_invalidation_hash,
    save_land_price_cache,
    save_resolve_cache,
    save_resolve_miss,
    save_sites_cache,
    set_geocode_deps_hash,
    set_land_price_deps_hash,
)
from src.land_db.schema import init_land_db


def _legacy_name(*parts: str) -> str:
    return "".join(parts)


_LEGACY_PRICE_CACHE = CACHE_DIR / _legacy_name("price_", "result_", "cache", ".json")
_LEGACY_GEOCODE_CACHE = CACHE_DIR / _legacy_name("geocode_", "result_", "cache", ".json")
_LEGACY_MARKET_CAP = CACHE_DIR / _legacy_name("market_", "cap_", "cache", ".json")
_LEGACY_COMPANY_META = CACHE_DIR / _legacy_name("company_", "master", ".yaml")
_LEGACY_FACILITIES_DIR = CACHE_DIR / _legacy_name("facilities_", "land")
_LEGACY_WEB_RESOLVE = WEB_ADDRESS_CACHE_DIR / _legacy_name("resolve_", "cache", ".json")
_LEGACY_ADDR_HASH = CACHE_DIR / _legacy_name("addr_", "overrides_", "hash", ".json")
_LEGACY_PRICE_HASH = CACHE_DIR / _legacy_name("price_", "overrides_", "hash", ".json")


def _migrate_price_cache(land_conn: "sqlite3.Connection") -> int:
    if not _LEGACY_PRICE_CACHE.exists():
        print("  legacy land price cache not found, skipping")
        return 0
    data = json.loads(_LEGACY_PRICE_CACHE.read_text(encoding="utf-8"))
    deps_hash = data.pop("_deps_hash", None)
    count = 0
    for key, value in data.items():
        if isinstance(value, dict):
            save_land_price_cache(land_conn, str(key), value)
            count += 1
    if deps_hash is not None:
        set_land_price_deps_hash(land_conn, str(deps_hash))
    land_conn.commit()
    return count


def _migrate_geocode_cache(land_conn: "sqlite3.Connection") -> int:
    if not _LEGACY_GEOCODE_CACHE.exists():
        print("  legacy geocode cache not found, skipping")
        return 0
    data = json.loads(_LEGACY_GEOCODE_CACHE.read_text(encoding="utf-8"))
    deps_hash = data.pop("_deps_hash", None)
    count = 0
    for address, coords in data.items():
        if isinstance(coords, list) and len(coords) == 3:
            save_geocode_cache(land_conn, str(address), float(coords[0]), float(coords[1]), str(coords[2]))
            count += 1
    if deps_hash is not None:
        set_geocode_deps_hash(land_conn, str(deps_hash))
    land_conn.commit()
    return count


def _migrate_facilities(land_conn: "sqlite3.Connection") -> int:
    if not _LEGACY_FACILITIES_DIR.exists():
        print("  legacy facilities cache not found, skipping")
        return 0
    count = 0
    for sites_file in sorted(_LEGACY_FACILITIES_DIR.glob("*" + _legacy_name("_sites", ".json"))):
        code = sites_file.stem.removesuffix(_legacy_name("_sites"))
        raw = json.loads(sites_file.read_text(encoding="utf-8"))
        cache_version = int(raw.get("cache_version", 0))
        pdf_size = int(raw.get("pdf_size", 0))
        pdf_mtime = float(raw.get("pdf_mtime", 0.0))
        sites = raw.get("sites", [])
        text_file = _LEGACY_FACILITIES_DIR / _legacy_name(code, "_facilities", "_text.txt")
        section_text = text_file.read_text(encoding="utf-8") if text_file.exists() else None
        save_sites_cache(
            land_conn,
            code,
            sites,
            cache_version=cache_version,
            pdf_size=pdf_size,
            pdf_mtime=pdf_mtime,
            section_text=section_text,
        )
        count += 1
    land_conn.commit()
    return count


def _migrate_web_resolve(land_conn: "sqlite3.Connection") -> int:
    if not _LEGACY_WEB_RESOLVE.exists():
        print("  legacy web-address cache not found, skipping")
        return 0
    data = json.loads(_LEGACY_WEB_RESOLVE.read_text(encoding="utf-8"))
    count = 0
    for resolve_key, entry in data.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("none") is True:
            save_resolve_miss(land_conn, str(resolve_key))
            count += 1
            continue
        if {"address", "score", "source_url"} <= set(entry):
            save_resolve_cache(
                land_conn,
                str(resolve_key),
                {
                    "address": str(entry["address"]),
                    "score": int(entry["score"]),
                    "source_url": str(entry["source_url"]),
                },
            )
            count += 1
    land_conn.commit()
    return count


def _migrate_hashes(land_conn: "sqlite3.Connection") -> int:
    migrated = 0
    for path, hash_type in [
        (_LEGACY_ADDR_HASH, "address_override"),
        (_LEGACY_PRICE_HASH, "price_override"),
    ]:
        if not path.exists():
            print(f"  legacy {hash_type} hash cache not found, skipping")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for code, hash_value in data.items():
            save_invalidation_hash(land_conn, hash_type, str(code), str(hash_value))
            migrated += 1
    land_conn.commit()
    return migrated


def _migrate_market_cap(stocks_conn: "sqlite3.Connection") -> int:
    from stock_db.storage.market_caps import upsert_market_cap

    if not _LEGACY_MARKET_CAP.exists():
        print("  legacy market-cap cache not found, skipping")
        return 0
    data = json.loads(_LEGACY_MARKET_CAP.read_text(encoding="utf-8"))
    count = 0
    for code, entry in data.items():
        if not isinstance(entry, dict):
            continue
        value_yen = entry.get("market_cap_yen")
        fetched_date = str(entry.get("fetched_date", ""))
        if value_yen is not None:
            upsert_market_cap(stocks_conn, str(code), "kabutan", int(value_yen), fetched_date)
            count += 1
    stocks_conn.commit()
    return count


def _migrate_company_metadata(stocks_conn: "sqlite3.Connection") -> int:
    if not _LEGACY_COMPANY_META.exists():
        print("  legacy company metadata YAML not found, skipping")
        return 0
    with _LEGACY_COMPANY_META.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    count = 0
    for code, entry in data.items():
        if not isinstance(entry, dict):
            continue
        code_str = str(code)
        name = str(entry.get("company_name", ""))
        pdf_url = entry.get("securities_report_pdf_url")
        source_urls = entry.get("address_source_urls")

        from src.company_store import merge_company_record

        merge_company_record(
            stocks_conn,
            code_str,
            company_name=name,
            securities_report_pdf_url=str(pdf_url) if pdf_url else "",
            address_source_urls=list(source_urls) if isinstance(source_urls, list) else [],
        )
        count += 1
    stocks_conn.commit()
    return count


def main() -> None:
    import sqlite3

    print(f"=== land.db migration ({LAND_DB_PATH}) ===")
    land_conn: sqlite3.Connection = get_connection(LAND_DB_PATH)
    init_land_db(land_conn)

    n = _migrate_price_cache(land_conn)
    print(f"  land price cache: {n} entries")

    n = _migrate_geocode_cache(land_conn)
    print(f"  geocode cache: {n} entries")

    n = _migrate_facilities(land_conn)
    print(f"  facilities cache: {n} entries")

    n = _migrate_web_resolve(land_conn)
    print(f"  web-address cache: {n} entries")

    n = _migrate_hashes(land_conn)
    print(f"  invalidation hashes: {n} entries")

    land_conn.close()

    print(f"\n=== stocks.db migration ({STOCKS_DB_PATH}) ===")
    stocks_conn: sqlite3.Connection = get_connection(STOCKS_DB_PATH)
    init_stocks_db(stocks_conn)

    n = _migrate_market_cap(stocks_conn)
    print(f"  market-cap rows: {n} entries")

    n = _migrate_company_metadata(stocks_conn)
    print(f"  company metadata rows: {n} entries")

    stocks_conn.close()
    print("\nmigration complete")


if __name__ == "__main__":
    main()
