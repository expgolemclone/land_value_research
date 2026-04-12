from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from stock_db.db.connection import get_connection

from land_db.schema import init_land_db
from land_db.repo import (
    load_land_price_cache,
    save_land_price_cache,
    get_land_price_deps_hash,
    set_land_price_deps_hash,
    load_geocode_cache,
    save_geocode_cache,
    get_geocode_deps_hash,
    set_geocode_deps_hash,
    load_sites_cache,
    save_sites_cache,
    load_resolve_cache,
    save_resolve_cache,
    load_invalidation_hash,
    save_invalidation_hash,
)


@pytest.fixture()
def land_conn(tmp_path: Path) -> sqlite3.Connection:
    conn = get_connection(tmp_path / "test_land.db")
    init_land_db(conn)
    yield conn
    conn.close()


class TestLandPriceCache:
    def test_save_and_load(self, land_conn: sqlite3.Connection) -> None:
        key = "35.706|139.775|idw|3|3|1.0|商業"
        value = {"unit_price": 3351455, "nearest_id": "13106-005-009"}

        save_land_price_cache(land_conn, key, value)
        land_conn.commit()
        result = load_land_price_cache(land_conn, key)

        assert result == value

    def test_load_missing_returns_none(self, land_conn: sqlite3.Connection) -> None:
        assert load_land_price_cache(land_conn, "nonexistent") is None

    def test_overwrite(self, land_conn: sqlite3.Connection) -> None:
        key = "35.706|139.775|idw|3|3|1.0|商業"
        save_land_price_cache(land_conn, key, {"unit_price": 100})
        save_land_price_cache(land_conn, key, {"unit_price": 200})
        land_conn.commit()

        result = load_land_price_cache(land_conn, key)
        assert result["unit_price"] == 200

    def test_deps_hash(self, land_conn: sqlite3.Connection) -> None:
        set_land_price_deps_hash(land_conn, "abc123")
        land_conn.commit()

        assert get_land_price_deps_hash(land_conn) == "abc123"


class TestGeocodeCache:
    def test_save_and_load(self, land_conn: sqlite3.Connection) -> None:
        address = "東京都台東区上野5丁目22番4号"

        save_geocode_cache(land_conn, address, 35.706289, 139.775384, "gaiku")
        land_conn.commit()
        result = load_geocode_cache(land_conn, address)

        assert result == (35.706289, 139.775384, "gaiku")

    def test_load_missing_returns_none(self, land_conn: sqlite3.Connection) -> None:
        assert load_geocode_cache(land_conn, "存在しない住所") is None

    def test_deps_hash(self, land_conn: sqlite3.Connection) -> None:
        set_geocode_deps_hash(land_conn, "def456")
        land_conn.commit()

        assert get_geocode_deps_hash(land_conn) == "def456"


class TestFacilitiesLand:
    def test_save_and_load(self, land_conn: sqlite3.Connection) -> None:
        code = "1234"
        sites = [
            {"site_name": "本社", "location_short": "東京都港区", "land_area_m2": 500.0,
             "land_book_value_yen": 1e9, "location_has_hoka": False, "equipment_type": ""},
        ]

        save_sites_cache(land_conn, code, sites, cache_version=5, pdf_size=12345, pdf_mtime=1700000000.0)
        land_conn.commit()
        result = load_sites_cache(land_conn, code, pdf_size=12345, pdf_mtime=1700000000.0)

        assert result is not None
        assert len(result) == 1
        assert result[0]["site_name"] == "本社"

    def test_load_returns_none_on_stale(self, land_conn: sqlite3.Connection) -> None:
        save_sites_cache(land_conn, "1234", [], cache_version=5, pdf_size=100, pdf_mtime=1.0)
        land_conn.commit()

        result = load_sites_cache(land_conn, "1234", pdf_size=999, pdf_mtime=1.0)

        assert result is None

    def test_load_missing_returns_none(self, land_conn: sqlite3.Connection) -> None:
        assert load_sites_cache(land_conn, "9999", pdf_size=0, pdf_mtime=0.0) is None


class TestWebAddressResolve:
    def test_save_and_load(self, land_conn: sqlite3.Connection) -> None:
        key = "本社|東京都千代田区|https://irbank.net/1234/ir"
        entry = {"address": "東京都千代田区丸の内1-4-5", "score": 80, "source_url": "https://example.com"}

        save_resolve_cache(land_conn, key, entry)
        land_conn.commit()
        result = load_resolve_cache(land_conn, key)

        assert result is not None
        assert result["address"] == "東京都千代田区丸の内1-4-5"
        assert result["score"] == 80

    def test_load_missing_returns_none(self, land_conn: sqlite3.Connection) -> None:
        assert load_resolve_cache(land_conn, "missing") is None


class TestInvalidationHashes:
    def test_save_and_load(self, land_conn: sqlite3.Connection) -> None:
        save_invalidation_hash(land_conn, "addr_overrides", "1234", "hash_abc")
        land_conn.commit()

        result = load_invalidation_hash(land_conn, "addr_overrides", "1234")

        assert result == "hash_abc"

    def test_load_missing_returns_none(self, land_conn: sqlite3.Connection) -> None:
        assert load_invalidation_hash(land_conn, "addr_overrides", "9999") is None

    def test_overwrite(self, land_conn: sqlite3.Connection) -> None:
        save_invalidation_hash(land_conn, "addr_overrides", "1234", "old")
        save_invalidation_hash(land_conn, "addr_overrides", "1234", "new")
        land_conn.commit()

        assert load_invalidation_hash(land_conn, "addr_overrides", "1234") == "new"
