#!/usr/bin/env python3
"""JSON/YAML キャッシュ → land.db + stocks.db マイグレーション.

- price_result_cache.json → land.db land_price_cache
- geocode_result_cache.json → land.db geocode_cache
- facilities_land/*.json → land.db facilities_land
- market_cap_cache.json → stocks.db market_cap
- company_master.yaml → stocks.db stocks (metadata fields)

Usage:
    PYTHONPATH=src uv run python scripts/migrate_to_land_db.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from src.config import (
    CACHE_DIR,
    COMPANY_MASTER_PATH,
    DATA_DIR,
    FACILITIES_CACHE_DIR,
    GEOCODE_CACHE_PATH,
    LAND_DB_PATH,
    MARKET_CAP_CACHE_PATH,
    PRICE_CACHE_PATH,
)
from stock_db.config import STOCKS_DB_PATH
from stock_db.db.connection import get_connection
from stock_db.db.repo import upsert_company_metadata, upsert_market_cap, upsert_stock
from stock_db.db.schema import init_db as init_stocks_db

from land_db.schema import init_land_db
from land_db.repo import (
    save_geocode_cache,
    save_land_price_cache,
    save_sites_cache,
    set_geocode_deps_hash,
    set_land_price_deps_hash,
)


def _migrate_price_cache(land_conn: 'sqlite3.Connection') -> int:
    if not PRICE_CACHE_PATH.exists():
        print("  price_result_cache.json not found, skipping")
        return 0
    data = json.loads(PRICE_CACHE_PATH.read_text(encoding="utf-8"))
    deps_hash = data.pop("_deps_hash", None)
    count = 0
    for key, value in data.items():
        save_land_price_cache(land_conn, key, value)
        count += 1
    if deps_hash is not None:
        set_land_price_deps_hash(land_conn, str(deps_hash))
    land_conn.commit()
    return count


def _migrate_geocode_cache(land_conn: 'sqlite3.Connection') -> int:
    if not GEOCODE_CACHE_PATH.exists():
        print("  geocode_result_cache.json not found, skipping")
        return 0
    data = json.loads(GEOCODE_CACHE_PATH.read_text(encoding="utf-8"))
    deps_hash = data.pop("_deps_hash", None)
    count = 0
    for address, coords in data.items():
        if not isinstance(coords, list) or len(coords) != 3:
            continue
        save_geocode_cache(land_conn, address, float(coords[0]), float(coords[1]), str(coords[2]))
        count += 1
    if deps_hash is not None:
        set_geocode_deps_hash(land_conn, str(deps_hash))
    land_conn.commit()
    return count


def _migrate_facilities(land_conn: 'sqlite3.Connection') -> int:
    if not FACILITIES_CACHE_DIR.exists():
        print("  facilities_land/ not found, skipping")
        return 0
    count = 0
    for json_file in sorted(FACILITIES_CACHE_DIR.glob("*_sites.json")):
        code = json_file.stem.replace("_sites", "")
        raw = json.loads(json_file.read_text(encoding="utf-8"))
        cache_version = raw.get("cache_version", 0)
        pdf_size = int(raw.get("pdf_size", 0))
        pdf_mtime = float(raw.get("pdf_mtime", 0.0))
        sites = raw.get("sites", [])
        save_sites_cache(
            land_conn, code, sites,
            cache_version=cache_version, pdf_size=pdf_size, pdf_mtime=pdf_mtime,
        )
        count += 1
    land_conn.commit()
    return count


def _migrate_market_cap(stocks_conn: 'sqlite3.Connection') -> int:
    if not MARKET_CAP_CACHE_PATH.exists():
        print("  market_cap_cache.json not found, skipping")
        return 0
    data = json.loads(MARKET_CAP_CACHE_PATH.read_text(encoding="utf-8"))
    count = 0
    for code, entry in data.items():
        if not isinstance(entry, dict):
            continue
        value_yen = entry.get("market_cap_yen")
        fetched_date = entry.get("fetched_date", "")
        if value_yen is not None:
            upsert_market_cap(stocks_conn, code, "kabutan", int(value_yen), str(fetched_date))
            count += 1
    stocks_conn.commit()
    return count


def _migrate_company_master(stocks_conn: 'sqlite3.Connection') -> int:
    if not COMPANY_MASTER_PATH.exists():
        print("  company_master.yaml not found, skipping")
        return 0
    with open(COMPANY_MASTER_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    count = 0
    for code, entry in data.items():
        if not isinstance(entry, dict):
            continue
        code_str = str(code)
        name = str(entry.get("company_name", ""))
        upsert_stock(stocks_conn, code_str, name, "", "")
        report_url = entry.get("securities_report_pdf_url")
        source_urls = entry.get("address_source_urls")
        upsert_company_metadata(
            stocks_conn, code_str,
            securities_report_url=str(report_url) if report_url else None,
            address_source_urls=json.dumps(source_urls, ensure_ascii=False) if source_urls else None,
        )
        count += 1
    stocks_conn.commit()
    return count


def main() -> None:
    import sqlite3

    print(f"=== land.db マイグレーション ({LAND_DB_PATH}) ===")
    land_conn: sqlite3.Connection = get_connection(LAND_DB_PATH)
    init_land_db(land_conn)

    n = _migrate_price_cache(land_conn)
    print(f"  land_price_cache: {n} entries")

    n = _migrate_geocode_cache(land_conn)
    print(f"  geocode_cache: {n} entries")

    n = _migrate_facilities(land_conn)
    print(f"  facilities_land: {n} entries")

    land_conn.close()

    print(f"\n=== stocks.db マイグレーション ({STOCKS_DB_PATH}) ===")
    stocks_conn: sqlite3.Connection = get_connection(STOCKS_DB_PATH)
    init_stocks_db(stocks_conn)

    n = _migrate_market_cap(stocks_conn)
    print(f"  market_cap: {n} entries")

    n = _migrate_company_master(stocks_conn)
    print(f"  company_master → stocks: {n} entries")

    stocks_conn.close()
    print("\nマイグレーション完了")


if __name__ == "__main__":
    main()
