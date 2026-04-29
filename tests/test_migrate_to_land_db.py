from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import yaml
from stock_db.storage.connection import get_connection
from stock_db.storage.market_caps import upsert_market_cap
from stock_db.storage.schema import init_db as init_stock_input_db
from stock_db.storage.stocks import upsert_company_metadata, upsert_stock

from scripts.migrate_to_land_db import LegacyPaths, execute
from src.company_store import connect_company_db, load_company_record, load_market_cap_snapshot
from src.land_db.repo import (
    get_geocode_deps_hash,
    get_land_price_deps_hash,
    load_facilities_cache,
    load_geocode_cache,
    load_invalidation_hash,
    load_land_price_cache,
    load_resolve_cache_record,
)
from src.land_db.schema import init_land_db


def _make_paths(tmp_path: Path) -> LegacyPaths:
    cache_dir = tmp_path / "cache"
    web_cache_dir = cache_dir / "web_address"
    cache_dir.mkdir(parents=True, exist_ok=True)
    web_cache_dir.mkdir(parents=True, exist_ok=True)
    return LegacyPaths.from_roots(
        cache_dir=cache_dir,
        web_address_cache_dir=web_cache_dir,
        land_db_path=tmp_path / "land.db",
        stocks_db_path=tmp_path / "stocks.db",
    )


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_yaml(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=True), encoding="utf-8")


def test_cleanup_migrates_project_metadata_into_land_db(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    _write_json(
        paths.price_cache,
        {
            "_deps_hash": "price-deps",
            "35.1|139.1": {"unit_price": 1234, "nearest_id": "A-1"},
        },
    )
    _write_json(
        paths.geocode_cache,
        {
            "_deps_hash": "geo-deps",
            "東京都千代田区丸の内1-1-1": [35.681, 139.767, "gaiku"],
        },
    )
    _write_json(
        paths.market_cap_cache,
        {
            "1234": {"market_cap_yen": 987654321, "fetched_date": "2026-04-28"},
        },
    )
    _write_yaml(
        paths.company_meta,
        {
            "1234": {
                "company_name": "テスト株式会社",
                "securities_report_pdf_url": "https://example.com/report.pdf",
                "address_source_urls": ["https://example.com/company"],
            }
        },
    )
    _write_json(paths.addr_hash, {"1234": "addr-hash"})
    _write_json(paths.price_hash, {"1234": "price-hash"})
    _write_json(
        paths.web_resolve,
        {
            "本社|東京都千代田区|https://example.com/company": {
                "address": "東京都千代田区丸の内1-1-1",
                "score": 88,
                "source_url": "https://example.com/source",
            },
            "工場|東京都港区|https://example.com/company": {
                "none": True,
            },
        },
    )
    keep_file = paths.web_address_cache_dir / "keep.analysis.json"
    keep_file.write_text("{}", encoding="utf-8")

    sites_file = paths.facilities_dir / "1234_sites.json"
    text_file = paths.facilities_dir / "1234_facilities_text.txt"
    _write_json(
        sites_file,
        {
            "cache_version": 5,
            "pdf_size": 321,
            "pdf_mtime": 1234.5,
            "sites": [
                {
                    "site_name": "本社",
                    "location_short": "東京都千代田区",
                    "land_area_m2": 100.0,
                    "land_book_value_yen": 500000000.0,
                    "location_has_hoka": False,
                    "equipment_type": "",
                }
            ],
        },
    )
    text_file.write_text("設備の状況", encoding="utf-8")

    rc = execute(paths, cleanup=True, dry_run=False)
    assert rc == 0

    assert not paths.price_cache.exists()
    assert not paths.geocode_cache.exists()
    assert not paths.market_cap_cache.exists()
    assert not paths.company_meta.exists()
    assert not paths.addr_hash.exists()
    assert not paths.price_hash.exists()
    assert not paths.web_resolve.exists()
    assert keep_file.exists()
    assert not sites_file.exists()
    assert not text_file.exists()
    assert not paths.facilities_dir.exists()
    assert not paths.stocks_db_path.exists()

    db = sqlite3.connect(paths.land_db_path)
    db.row_factory = sqlite3.Row
    try:
        init_land_db(db)
        assert get_land_price_deps_hash(db) == "price-deps"
        assert load_land_price_cache(db, "35.1|139.1") == {"unit_price": 1234, "nearest_id": "A-1"}
        assert get_geocode_deps_hash(db) == "geo-deps"
        assert load_geocode_cache(db, "東京都千代田区丸の内1-1-1") == (35.681, 139.767, "gaiku")
        assert load_invalidation_hash(db, "address_override", "1234") == "addr-hash"
        assert load_invalidation_hash(db, "price_override", "1234") == "price-hash"
        assert load_resolve_cache_record(db, "本社|東京都千代田区|https://example.com/company") == {
            "resolved": True,
            "address": "東京都千代田区丸の内1-1-1",
            "score": 88,
            "source_url": "https://example.com/source",
        }
        assert load_resolve_cache_record(db, "工場|東京都港区|https://example.com/company") == {"resolved": False}
        facilities = load_facilities_cache(db, "1234", pdf_size=321, pdf_mtime=1234.5)
        assert facilities is not None
        assert facilities[1] == "設備の状況"
    finally:
        db.close()

    company_conn = connect_company_db(paths.land_db_path)
    try:
        assert load_market_cap_snapshot(company_conn, "1234") == {
            "market_cap_yen": 987654321,
            "fetched_date": "2026-04-28",
        }
        assert load_company_record(company_conn, "1234") == {
            "company_name": "テスト株式会社",
            "securities_report_pdf_url": "https://example.com/report.pdf",
            "address_source_urls": ["https://example.com/company"],
        }
    finally:
        company_conn.close()


def test_cleanup_accepts_facilities_cache_without_text_file(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    _write_json(
        paths.facilities_dir / "5678_sites.json",
        {
            "cache_version": 5,
            "pdf_size": 999,
            "pdf_mtime": 55.5,
            "sites": [],
        },
    )

    rc = execute(paths, cleanup=True, dry_run=False)
    assert rc == 0
    assert not paths.facilities_dir.exists()


def test_migration_can_read_project_metadata_from_stocks_input_only(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    stocks_input_conn = get_connection(paths.stocks_db_path)
    init_stock_input_db(stocks_input_conn)
    upsert_stock(stocks_input_conn, "1431", "Lib Work", "", "")
    upsert_company_metadata(
        stocks_input_conn,
        "1431",
        securities_report_url="https://example.com/report.pdf",
        address_source_urls='["https://example.com/company"]',
    )
    upsert_market_cap(stocks_input_conn, "1431", "kabutan", 123456789, "2026-04-28")
    stocks_input_conn.commit()
    stocks_input_conn.close()

    rc = execute(paths, cleanup=True, dry_run=False)
    assert rc == 0
    assert paths.stocks_db_path.exists()

    company_conn = connect_company_db(paths.land_db_path)
    try:
        assert load_company_record(company_conn, "1431") == {
            "company_name": "Lib Work",
            "securities_report_pdf_url": "https://example.com/report.pdf",
            "address_source_urls": ["https://example.com/company"],
        }
        assert load_market_cap_snapshot(company_conn, "1431") == {
            "market_cap_yen": 123456789,
            "fetched_date": "2026-04-28",
        }
    finally:
        company_conn.close()


def test_dry_run_is_non_destructive_and_reports_cleanup_targets(tmp_path: Path, capsys) -> None:
    paths = _make_paths(tmp_path)
    _write_json(paths.price_cache, {"_deps_hash": "price-deps", "k": {"unit_price": 1}})
    _write_json(paths.addr_hash, {"1234": "addr-hash"})

    rc = execute(paths, cleanup=True, dry_run=True)
    assert rc == 0
    assert paths.price_cache.exists()
    assert paths.addr_hash.exists()
    assert not paths.land_db_path.exists()
    assert not paths.stocks_db_path.exists()

    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "delete file:" in out


def test_cleanup_fails_when_text_file_has_no_matching_sites_json(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    text_file = paths.facilities_dir / "9999_facilities_text.txt"
    text_file.parent.mkdir(parents=True, exist_ok=True)
    text_file.write_text("孤立した設備テキスト", encoding="utf-8")

    rc = execute(paths, cleanup=True, dry_run=False)
    assert rc == 1
    assert text_file.exists()
    assert paths.facilities_dir.exists()
