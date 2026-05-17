from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from stock_db.storage.connection import get_connection

from src.land_db.repo import (
    delete_invalidation_hash,
    get_geocode_deps_hash,
    get_land_price_deps_hash,
    list_invalidation_hashes,
    load_facilities_cache,
    load_facilities_section_text,
    load_geocode_cache,
    load_invalidation_hash,
    load_land_price_cache,
    load_resolve_cache,
    load_resolve_cache_record,
    save_facilities_section_text,
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

    def test_deps_hash(self, land_conn: sqlite3.Connection) -> None:
        set_land_price_deps_hash(land_conn, "abc123")
        land_conn.commit()
        assert get_land_price_deps_hash(land_conn) == "abc123"


class TestGeocodeCache:
    def test_save_and_load(self, land_conn: sqlite3.Connection) -> None:
        address = "東京都台東区上野5丁目22番4号"
        save_geocode_cache(land_conn, address, 35.706289, 139.775384, "gaiku")
        land_conn.commit()
        assert load_geocode_cache(land_conn, address) == (35.706289, 139.775384, "gaiku")

    def test_deps_hash(self, land_conn: sqlite3.Connection) -> None:
        set_geocode_deps_hash(land_conn, "def456")
        land_conn.commit()
        assert get_geocode_deps_hash(land_conn) == "def456"


class TestFacilitiesCache:
    def test_save_and_load(self, land_conn: sqlite3.Connection) -> None:
        code = "1234"
        sites = [
            {
                "site_name": "本社",
                "location_short": "東京都港区",
                "land_area_m2": 500.0,
                "land_book_value_yen": 1e9,
                "location_has_hoka": False,
                "equipment_type": "",
            },
        ]

        save_sites_cache(
            land_conn,
            code,
            sites,
            cache_version=5,
            source_kind="xbrl",
            source_id="S100TEST",
            source_size=12345,
            source_mtime_ns=1_700_000_000_000_000_000,
            section_text="設備の状況テキスト",
        )
        land_conn.commit()

        result = load_facilities_cache(
            land_conn,
            code,
            cache_version=5,
            source_kind="xbrl",
            source_id="S100TEST",
            source_size=12345,
            source_mtime_ns=1_700_000_000_000_000_000,
        )
        assert result is not None
        loaded_sites, loaded_text = result
        assert loaded_sites[0]["site_name"] == "本社"
        assert loaded_text == "設備の状況テキスト"

    def test_cache_misses_on_source_or_version_change(self, land_conn: sqlite3.Connection) -> None:
        save_sites_cache(
            land_conn,
            "1234",
            [],
            cache_version=5,
            source_kind="xbrl",
            source_id="S100OLD",
            source_size=100,
            source_mtime_ns=1,
        )
        land_conn.commit()

        assert (
            load_facilities_cache(
                land_conn,
                "1234",
                cache_version=6,
                source_kind="xbrl",
                source_id="S100OLD",
                source_size=100,
                source_mtime_ns=1,
            )
            is None
        )
        assert (
            load_facilities_cache(
                land_conn,
                "1234",
                cache_version=5,
                source_kind="xbrl",
                source_id="S100NEW",
                source_size=100,
                source_mtime_ns=1,
            )
            is None
        )

    def test_section_text_can_be_written_later(self, land_conn: sqlite3.Connection) -> None:
        save_sites_cache(
            land_conn,
            "1234",
            [],
            cache_version=5,
            source_kind="xbrl",
            source_id="S100TEST",
            source_size=100,
            source_mtime_ns=1,
        )
        save_facilities_section_text(
            land_conn,
            "1234",
            "追記テキスト",
            cache_version=5,
            source_kind="xbrl",
            source_id="S100TEST",
            source_size=100,
            source_mtime_ns=1,
        )
        land_conn.commit()

        assert (
            load_facilities_section_text(
                land_conn,
                "1234",
                cache_version=5,
                source_kind="xbrl",
                source_id="S100TEST",
                source_size=100,
                source_mtime_ns=1,
            )
            == "追記テキスト"
        )


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

    def test_save_and_load_negative_cache(self, land_conn: sqlite3.Connection) -> None:
        save_resolve_miss(land_conn, "missing-key")
        land_conn.commit()

        record = load_resolve_cache_record(land_conn, "missing-key")
        assert record == {"resolved": False}
        assert load_resolve_cache(land_conn, "missing-key") is None

    def test_migrates_legacy_not_null_miss_fields(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "legacy_land.db")
        conn.executescript(
            """
            CREATE TABLE web_address_resolve (
                resolve_key TEXT PRIMARY KEY,
                address     TEXT NOT NULL,
                score       INTEGER NOT NULL,
                source_url  TEXT NOT NULL
            );

            INSERT INTO web_address_resolve (
                resolve_key,
                address,
                score,
                source_url
            )
            VALUES (
                'hit-key',
                '東京都千代田区丸の内1-4-5',
                80,
                'https://example.com'
            );
            """
        )
        conn.commit()

        try:
            init_land_db(conn)
            info = {
                str(row["name"]): int(row["notnull"])
                for row in conn.execute("PRAGMA table_info(web_address_resolve)").fetchall()
            }

            assert info["address"] == 0
            assert info["score"] == 0
            assert info["source_url"] == 0

            save_resolve_miss(conn, "missing-key")
            conn.commit()

            assert load_resolve_cache_record(conn, "missing-key") == {"resolved": False}
            assert load_resolve_cache(conn, "missing-key") is None
        finally:
            conn.close()


class TestInvalidationHashes:
    def test_save_list_delete(self, land_conn: sqlite3.Connection) -> None:
        save_invalidation_hash(land_conn, "address_override", "1234", "hash_abc")
        save_invalidation_hash(land_conn, "address_override", "5678", "hash_def")
        land_conn.commit()

        assert load_invalidation_hash(land_conn, "address_override", "1234") == "hash_abc"
        assert list_invalidation_hashes(land_conn, "address_override") == {
            "1234": "hash_abc",
            "5678": "hash_def",
        }

        delete_invalidation_hash(land_conn, "address_override", "1234")
        land_conn.commit()
        assert load_invalidation_hash(land_conn, "address_override", "1234") is None


class TestSchemaMigration:
    def test_adds_xbrl_source_columns_to_legacy_facilities_land(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "legacy_facilities.db")
        try:
            conn.executescript(
                """
                CREATE TABLE facilities_land (
                    code           TEXT PRIMARY KEY,
                    sites_json     TEXT NOT NULL,
                    section_text   TEXT,
                    cache_version  INTEGER NOT NULL,
                    pdf_size       INTEGER,
                    pdf_mtime      REAL,
                    updated_at     TEXT NOT NULL
                );
                INSERT INTO facilities_land (
                    code, sites_json, section_text, cache_version, pdf_size, pdf_mtime, updated_at
                )
                VALUES ('1234', '[]', NULL, 5, 100, 1.0, '2026-04-29T00:00:00+00:00');
                """
            )
            conn.commit()

            init_land_db(conn)

            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(facilities_land)").fetchall()}
            assert {"source_kind", "source_id", "source_size", "source_mtime_ns"} <= columns
        finally:
            conn.close()

    def test_removes_legacy_company_metadata_columns_and_market_cap_cache(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "legacy_land.db")
        try:
            conn.executescript(
                """
                CREATE TABLE company_metadata (
                    code TEXT PRIMARY KEY,
                    company_name TEXT NOT NULL DEFAULT '',
                    securities_report_pdf_url TEXT NOT NULL DEFAULT '',
                    address_source_urls TEXT,
                    updated_at TEXT NOT NULL
                );

                INSERT INTO company_metadata (
                    code,
                    company_name,
                    securities_report_pdf_url,
                    address_source_urls,
                    updated_at
                )
                VALUES (
                    '1234',
                    'テスト株式会社',
                    'https://example.com/report.pdf',
                    '["https://example.com/company"]',
                    '2026-04-29T00:00:00+00:00'
                );

                CREATE TABLE market_cap_cache (
                    code TEXT NOT NULL,
                    source TEXT NOT NULL,
                    market_cap_yen INTEGER NOT NULL,
                    fetched_date TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (code, source)
                );

                INSERT INTO market_cap_cache (
                    code,
                    source,
                    market_cap_yen,
                    fetched_date,
                    updated_at
                )
                VALUES (
                    '1234',
                    'kabutan',
                    100000000,
                    '2026-04-29',
                    '2026-04-29T00:00:00+00:00'
                );
                """
            )
            conn.commit()

            init_land_db(conn)

            company_columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(company_metadata)").fetchall()
            }
            assert "address_source_urls" not in company_columns

            row = conn.execute(
                """
                SELECT code, company_name, securities_report_pdf_url, updated_at
                FROM company_metadata
                WHERE code = ?
                """,
                ("1234",),
            ).fetchone()
            assert row is not None
            assert row["company_name"] == "テスト株式会社"
            assert row["securities_report_pdf_url"] == "https://example.com/report.pdf"

            market_cap_table = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = 'market_cap_cache'
                """
            ).fetchone()
            assert market_cap_table is None
        finally:
            conn.close()
