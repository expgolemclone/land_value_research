#!/usr/bin/env python3
"""Migrate legacy project-owned cache artifacts into land.db."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from stock_db.paths import STOCKS_DB_PATH
from stock_db.storage.connection import get_connection

from src.company_store import (
    load_company_record,
    load_market_cap_snapshot,
    merge_company_record,
    save_market_cap_snapshot,
)
from src.config import CACHE_DIR, LAND_DB_PATH, WEB_ADDRESS_CACHE_DIR
from src.land_db.repo import (
    get_geocode_deps_hash,
    get_land_price_deps_hash,
    load_facilities_cache,
    load_geocode_cache,
    load_invalidation_hash,
    load_land_price_cache,
    load_resolve_cache_record,
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


@dataclass(frozen=True)
class LegacyPaths:
    land_db_path: Path
    stocks_db_path: Path
    cache_dir: Path
    web_address_cache_dir: Path
    price_cache: Path
    geocode_cache: Path
    market_cap_cache: Path
    company_meta: Path
    facilities_dir: Path
    web_resolve: Path
    addr_hash: Path
    price_hash: Path

    @classmethod
    def defaults(cls) -> "LegacyPaths":
        return cls.from_roots(
            cache_dir=CACHE_DIR,
            web_address_cache_dir=WEB_ADDRESS_CACHE_DIR,
            land_db_path=LAND_DB_PATH,
            stocks_db_path=STOCKS_DB_PATH,
        )

    @classmethod
    def from_roots(
        cls,
        *,
        cache_dir: Path,
        web_address_cache_dir: Path,
        land_db_path: Path,
        stocks_db_path: Path,
    ) -> "LegacyPaths":
        return cls(
            land_db_path=land_db_path,
            stocks_db_path=stocks_db_path,
            cache_dir=cache_dir,
            web_address_cache_dir=web_address_cache_dir,
            price_cache=cache_dir / _legacy_name("price_", "result_", "cache", ".json"),
            geocode_cache=cache_dir / _legacy_name("geocode_", "result_", "cache", ".json"),
            market_cap_cache=cache_dir / _legacy_name("market_", "cap_", "cache", ".json"),
            company_meta=cache_dir / _legacy_name("company_", "master", ".yaml"),
            facilities_dir=cache_dir / _legacy_name("facilities_", "land"),
            web_resolve=web_address_cache_dir / _legacy_name("resolve_", "cache", ".json"),
            addr_hash=cache_dir / _legacy_name("addr_", "overrides_", "hash", ".json"),
            price_hash=cache_dir / _legacy_name("price_", "overrides_", "hash", ".json"),
        )


@dataclass
class MigrationStats:
    land_price_cache: int = 0
    geocode_cache: int = 0
    facilities_cache: int = 0
    web_address_cache: int = 0
    invalidation_hashes: int = 0
    market_cap_rows: int = 0
    company_metadata_rows: int = 0


@dataclass
class CleanupPlan:
    files_to_delete: list[Path] = field(default_factory=list)
    dirs_to_delete: list[Path] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def add_file(self, path: Path) -> None:
        if path not in self.files_to_delete:
            self.files_to_delete.append(path)

    def add_dir(self, path: Path) -> None:
        if path not in self.dirs_to_delete:
            self.dirs_to_delete.append(path)

    @property
    def ok(self) -> bool:
        return not self.failures


def _load_json_file(path: Path) -> object:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _load_yaml_mapping(path: Path) -> dict[object, object]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"expected mapping YAML: {path}")
    return data


def _decode_urls(raw: object) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, str):
        return []
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    return [str(url) for url in loaded if str(url).strip()]


def _normalize_fetched_date(raw: object) -> str:
    return str(raw or "")[:10]


def _copy_db_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _create_dry_run_paths(paths: LegacyPaths) -> tuple[tempfile.TemporaryDirectory[str], LegacyPaths]:
    tempdir = tempfile.TemporaryDirectory(prefix="migrate_to_land_db_")
    tmp_root = Path(tempdir.name)
    land_db_path = tmp_root / "land.db"
    _copy_db_if_exists(paths.land_db_path, land_db_path)
    return (
        tempdir,
        LegacyPaths(
            land_db_path=land_db_path,
            stocks_db_path=paths.stocks_db_path,
            cache_dir=paths.cache_dir,
            web_address_cache_dir=paths.web_address_cache_dir,
            price_cache=paths.price_cache,
            geocode_cache=paths.geocode_cache,
            market_cap_cache=paths.market_cap_cache,
            company_meta=paths.company_meta,
            facilities_dir=paths.facilities_dir,
            web_resolve=paths.web_resolve,
            addr_hash=paths.addr_hash,
            price_hash=paths.price_hash,
        ),
    )


def _migrate_price_cache(land_conn: sqlite3.Connection, path: Path) -> int:
    if not path.exists():
        print("  legacy land price cache not found, skipping")
        return 0
    data = _load_json_file(path)
    if not isinstance(data, dict):
        raise ValueError(f"legacy land price cache must be a JSON object: {path}")
    deps_hash = data.pop("_deps_hash", None)
    count = 0
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        save_land_price_cache(land_conn, str(key), value)
        count += 1
    if deps_hash is not None:
        set_land_price_deps_hash(land_conn, str(deps_hash))
    land_conn.commit()
    return count


def _migrate_geocode_cache(land_conn: sqlite3.Connection, path: Path) -> int:
    if not path.exists():
        print("  legacy geocode cache not found, skipping")
        return 0
    data = _load_json_file(path)
    if not isinstance(data, dict):
        raise ValueError(f"legacy geocode cache must be a JSON object: {path}")
    deps_hash = data.pop("_deps_hash", None)
    count = 0
    for address, coords in data.items():
        if not isinstance(coords, list) or len(coords) != 3:
            continue
        save_geocode_cache(land_conn, str(address), float(coords[0]), float(coords[1]), str(coords[2]))
        count += 1
    if deps_hash is not None:
        set_geocode_deps_hash(land_conn, str(deps_hash))
    land_conn.commit()
    return count


def _migrate_facilities(land_conn: sqlite3.Connection, facilities_dir: Path) -> int:
    if not facilities_dir.exists():
        print("  legacy facilities cache not found, skipping")
        return 0
    count = 0
    for sites_file in sorted(facilities_dir.glob("*" + _legacy_name("_sites", ".json"))):
        code = sites_file.stem.removesuffix(_legacy_name("_sites"))
        raw = _load_json_file(sites_file)
        if not isinstance(raw, dict):
            raise ValueError(f"legacy facilities cache must be a JSON object: {sites_file}")
        cache_version = int(raw.get("cache_version", 0))
        pdf_size = int(raw.get("pdf_size", 0))
        pdf_mtime = float(raw.get("pdf_mtime", 0.0))
        sites = raw.get("sites", [])
        if not isinstance(sites, list):
            raise ValueError(f"legacy facilities sites must be a list: {sites_file}")
        text_file = facilities_dir / _legacy_name(code, "_facilities", "_text.txt")
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


def _migrate_web_resolve(land_conn: sqlite3.Connection, path: Path) -> int:
    if not path.exists():
        print("  legacy web-address cache not found, skipping")
        return 0
    data = _load_json_file(path)
    if not isinstance(data, dict):
        raise ValueError(f"legacy web-address cache must be a JSON object: {path}")
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


def _migrate_hashes(land_conn: sqlite3.Connection, paths: LegacyPaths) -> int:
    migrated = 0
    for path, hash_type in [
        (paths.addr_hash, "address_override"),
        (paths.price_hash, "price_override"),
    ]:
        if not path.exists():
            print(f"  legacy {hash_type} hash cache not found, skipping")
            continue
        data = _load_json_file(path)
        if not isinstance(data, dict):
            raise ValueError(f"legacy invalidation hash cache must be a JSON object: {path}")
        for code, hash_value in data.items():
            save_invalidation_hash(land_conn, hash_type, str(code), str(hash_value))
            migrated += 1
    land_conn.commit()
    return migrated


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _save_market_cap_if_newer(
    land_conn: sqlite3.Connection,
    code: str,
    source: str,
    market_cap_yen: int,
    fetched_date: object,
) -> bool:
    normalized_fetched_date = _normalize_fetched_date(fetched_date)
    row = land_conn.execute(
        """
        SELECT fetched_date
        FROM market_cap_cache
        WHERE code = ? AND source = ?
        """,
        (code, source),
    ).fetchone()
    if row is not None:
        existing_fetched_date = _normalize_fetched_date(row["fetched_date"])
        if existing_fetched_date and normalized_fetched_date and normalized_fetched_date < existing_fetched_date:
            return False
        if existing_fetched_date and not normalized_fetched_date:
            return False
    save_market_cap_snapshot(
        land_conn,
        code,
        market_cap_yen,
        normalized_fetched_date,
        source=source,
    )
    return True


def _migrate_market_cap_from_legacy(land_conn: sqlite3.Connection, path: Path) -> int:
    data = _load_json_file(path)
    if not isinstance(data, dict):
        raise ValueError(f"legacy market-cap cache must be a JSON object: {path}")
    count = 0
    for code, entry in data.items():
        if not isinstance(entry, dict):
            continue
        value_yen = entry.get("market_cap_yen")
        if value_yen is None:
            continue
        if _save_market_cap_if_newer(land_conn, str(code), "kabutan", int(value_yen), entry.get("fetched_date", "")):
            count += 1
    land_conn.commit()
    return count


def _migrate_market_cap_from_stocks_input(land_conn: sqlite3.Connection, stocks_db_path: Path) -> int:
    if not stocks_db_path.exists():
        return 0
    stocks_conn = get_connection(stocks_db_path)
    try:
        if not _table_exists(stocks_conn, "market_cap"):
            return 0
        rows = stocks_conn.execute(
            """
            SELECT ticker, source, value_yen, fetched_at
            FROM market_cap
            WHERE value_yen IS NOT NULL
            ORDER BY ticker, source
            """
        ).fetchall()
        count = 0
        for row in rows:
            if _save_market_cap_if_newer(
                land_conn,
                str(row["ticker"]),
                str(row["source"]),
                int(row["value_yen"]),
                row["fetched_at"],
            ):
                count += 1
        land_conn.commit()
        return count
    finally:
        stocks_conn.close()


def _migrate_market_cap(land_conn: sqlite3.Connection, paths: LegacyPaths) -> int:
    count = _migrate_market_cap_from_stocks_input(land_conn, paths.stocks_db_path)
    if not paths.market_cap_cache.exists():
        print("  legacy market-cap cache not found, skipping")
        return count
    return count + _migrate_market_cap_from_legacy(land_conn, paths.market_cap_cache)


def _migrate_company_metadata_from_legacy(land_conn: sqlite3.Connection, path: Path) -> int:
    data = _load_yaml_mapping(path)
    count = 0
    for code, entry in data.items():
        if not isinstance(entry, dict):
            continue
        pdf_url = entry.get("securities_report_pdf_url")
        source_urls = entry.get("address_source_urls")
        merge_company_record(
            land_conn,
            str(code),
            company_name=str(entry.get("company_name", "") or ""),
            securities_report_pdf_url=str(pdf_url) if pdf_url else "",
            address_source_urls=list(source_urls) if isinstance(source_urls, list) else [],
        )
        count += 1
    land_conn.commit()
    return count


def _migrate_company_metadata_from_stocks_input(land_conn: sqlite3.Connection, stocks_db_path: Path) -> int:
    if not stocks_db_path.exists():
        return 0
    stocks_conn = get_connection(stocks_db_path)
    try:
        if not _table_exists(stocks_conn, "stocks"):
            return 0
        rows = stocks_conn.execute(
            """
            SELECT ticker, name, securities_report_url, address_source_urls
            FROM stocks
            WHERE COALESCE(name, '') <> ''
               OR COALESCE(securities_report_url, '') <> ''
               OR COALESCE(address_source_urls, '') <> ''
            ORDER BY ticker
            """
        ).fetchall()
        for row in rows:
            merge_company_record(
                land_conn,
                str(row["ticker"]),
                company_name=str(row["name"] or ""),
                securities_report_pdf_url=str(row["securities_report_url"] or ""),
                address_source_urls=_decode_urls(row["address_source_urls"]),
            )
        land_conn.commit()
        return len(rows)
    finally:
        stocks_conn.close()


def _migrate_company_metadata(land_conn: sqlite3.Connection, paths: LegacyPaths) -> int:
    count = _migrate_company_metadata_from_stocks_input(land_conn, paths.stocks_db_path)
    if not paths.company_meta.exists():
        print("  legacy company metadata YAML not found, skipping")
        return count
    return count + _migrate_company_metadata_from_legacy(land_conn, paths.company_meta)


def _run_migration(paths: LegacyPaths) -> MigrationStats:
    stats = MigrationStats()

    print(f"=== land.db migration ({paths.land_db_path}) ===")
    land_conn = get_connection(paths.land_db_path)
    try:
        init_land_db(land_conn)
        stats.land_price_cache = _migrate_price_cache(land_conn, paths.price_cache)
        print(f"  land price cache: {stats.land_price_cache} entries")

        stats.geocode_cache = _migrate_geocode_cache(land_conn, paths.geocode_cache)
        print(f"  geocode cache: {stats.geocode_cache} entries")

        stats.facilities_cache = _migrate_facilities(land_conn, paths.facilities_dir)
        print(f"  facilities cache: {stats.facilities_cache} entries")

        stats.web_address_cache = _migrate_web_resolve(land_conn, paths.web_resolve)
        print(f"  web-address cache: {stats.web_address_cache} entries")

        stats.invalidation_hashes = _migrate_hashes(land_conn, paths)
        print(f"  invalidation hashes: {stats.invalidation_hashes} entries")

        stats.market_cap_rows = _migrate_market_cap(land_conn, paths)
        print(f"  market-cap rows: {stats.market_cap_rows} entries")

        stats.company_metadata_rows = _migrate_company_metadata(land_conn, paths)
        print(f"  company metadata rows: {stats.company_metadata_rows} entries")
    finally:
        land_conn.close()

    print("\n=== stocks.db input-only policy ===")

    print("\nmigration complete")
    return stats


def _expected_resolve_record(entry: dict[object, object]) -> dict[str, object] | None:
    if entry.get("none") is True:
        return {"resolved": False}
    if {"address", "score", "source_url"} <= set(entry):
        return {
            "resolved": True,
            "address": str(entry["address"]),
            "score": int(entry["score"]),
            "source_url": str(entry["source_url"]),
        }
    return None


def _verify_json_mapping_file(
    path: Path,
    plan: CleanupPlan,
    verifier: Callable[[dict[object, object]], list[str]],
) -> None:
    if not path.exists():
        return
    data = _load_json_file(path)
    if not isinstance(data, dict):
        plan.failures.append(f"{path}: JSON object ではありません")
        return
    failures = verifier(data)
    if failures:
        plan.failures.extend(failures)
        return
    plan.add_file(path)


def _verify_yaml_file(
    path: Path,
    plan: CleanupPlan,
    verifier: Callable[[dict[object, object]], list[str]],
) -> None:
    if not path.exists():
        return
    try:
        data = _load_yaml_mapping(path)
    except ValueError as exc:
        plan.failures.append(str(exc))
        return
    failures = verifier(data)
    if failures:
        plan.failures.extend(failures)
        return
    plan.add_file(path)


def _plan_cleanup(paths: LegacyPaths) -> CleanupPlan:
    plan = CleanupPlan()
    land_conn = get_connection(paths.land_db_path)
    try:
        init_land_db(land_conn)

        def verify_price_cache(data: dict[object, object]) -> list[str]:
            failures: list[str] = []
            deps_hash = data.get("_deps_hash")
            if deps_hash is not None and get_land_price_deps_hash(land_conn) != str(deps_hash):
                failures.append(f"{paths.price_cache}: land_price deps_hash が一致しません")
            for key, value in data.items():
                if key == "_deps_hash":
                    continue
                if not isinstance(value, dict):
                    failures.append(f"{paths.price_cache}: {key} の値が dict ではありません")
                    continue
                loaded = load_land_price_cache(land_conn, str(key))
                if loaded != value:
                    failures.append(f"{paths.price_cache}: {key} の land_price_cache が一致しません")
            return failures

        def verify_geocode_cache(data: dict[object, object]) -> list[str]:
            failures: list[str] = []
            deps_hash = data.get("_deps_hash")
            if deps_hash is not None and get_geocode_deps_hash(land_conn) != str(deps_hash):
                failures.append(f"{paths.geocode_cache}: geocode deps_hash が一致しません")
            for address, coords in data.items():
                if address == "_deps_hash":
                    continue
                if not isinstance(coords, list) or len(coords) != 3:
                    failures.append(f"{paths.geocode_cache}: {address} の値が [lat, lon, level] ではありません")
                    continue
                loaded = load_geocode_cache(land_conn, str(address))
                expected = (float(coords[0]), float(coords[1]), str(coords[2]))
                if loaded != expected:
                    failures.append(f"{paths.geocode_cache}: {address} の geocode_cache が一致しません")
            return failures

        def verify_hash_cache(hash_type: str, path: Path, data: dict[object, object]) -> list[str]:
            failures: list[str] = []
            for code, hash_value in data.items():
                loaded = load_invalidation_hash(land_conn, hash_type, str(code))
                if loaded != str(hash_value):
                    failures.append(f"{path}: {hash_type}/{code} の hash が一致しません")
            return failures

        def verify_web_resolve(data: dict[object, object]) -> list[str]:
            failures: list[str] = []
            for resolve_key, entry in data.items():
                if not isinstance(entry, dict):
                    failures.append(f"{paths.web_resolve}: {resolve_key} の値が dict ではありません")
                    continue
                expected = _expected_resolve_record(entry)
                if expected is None:
                    failures.append(f"{paths.web_resolve}: {resolve_key} の値が未対応形式です")
                    continue
                loaded = load_resolve_cache_record(land_conn, str(resolve_key))
                if loaded != expected:
                    failures.append(f"{paths.web_resolve}: {resolve_key} の web-address cache が一致しません")
            return failures

        def verify_market_cap_cache(data: dict[object, object]) -> list[str]:
            failures: list[str] = []
            for code, entry in data.items():
                if not isinstance(entry, dict):
                    failures.append(f"{paths.market_cap_cache}: {code} の値が dict ではありません")
                    continue
                value_yen = entry.get("market_cap_yen")
                if value_yen is None:
                    failures.append(f"{paths.market_cap_cache}: {code} に market_cap_yen がありません")
                    continue
                fetched_date = str(entry.get("fetched_date", ""))
                snapshot = load_market_cap_snapshot(land_conn, str(code))
                if snapshot is None:
                    failures.append(f"{paths.market_cap_cache}: {code} の market_cap が見つかりません")
                    continue
                if snapshot["market_cap_yen"] != int(value_yen) or snapshot["fetched_date"] != fetched_date[:10]:
                    failures.append(f"{paths.market_cap_cache}: {code} の market_cap が一致しません")
            return failures

        def verify_company_meta(data: dict[object, object]) -> list[str]:
            failures: list[str] = []
            for code, entry in data.items():
                if not isinstance(entry, dict):
                    failures.append(f"{paths.company_meta}: {code} の値が dict ではありません")
                    continue
                record = load_company_record(land_conn, str(code))
                company_name = str(entry.get("company_name", "") or "")
                if company_name and record.get("company_name") != company_name:
                    failures.append(f"{paths.company_meta}: {code} の company_name が一致しません")
                pdf_url = str(entry.get("securities_report_pdf_url", "") or "")
                if pdf_url and record.get("securities_report_pdf_url") != pdf_url:
                    failures.append(f"{paths.company_meta}: {code} の securities_report_pdf_url が一致しません")
                source_urls = entry.get("address_source_urls")
                if isinstance(source_urls, list) and source_urls and record.get("address_source_urls") != list(source_urls):
                    failures.append(f"{paths.company_meta}: {code} の address_source_urls が一致しません")
            return failures

        _verify_json_mapping_file(paths.price_cache, plan, verify_price_cache)
        _verify_json_mapping_file(paths.geocode_cache, plan, verify_geocode_cache)
        _verify_json_mapping_file(paths.market_cap_cache, plan, verify_market_cap_cache)
        _verify_json_mapping_file(
            paths.addr_hash,
            plan,
            lambda data: verify_hash_cache("address_override", paths.addr_hash, data),
        )
        _verify_json_mapping_file(
            paths.price_hash,
            plan,
            lambda data: verify_hash_cache("price_override", paths.price_hash, data),
        )
        _verify_json_mapping_file(paths.web_resolve, plan, verify_web_resolve)
        _verify_yaml_file(paths.company_meta, plan, verify_company_meta)

        if paths.facilities_dir.exists():
            seen_text_files: set[Path] = set()
            for sites_file in sorted(paths.facilities_dir.glob("*" + _legacy_name("_sites", ".json"))):
                code = sites_file.stem.removesuffix(_legacy_name("_sites"))
                raw = _load_json_file(sites_file)
                if not isinstance(raw, dict):
                    plan.failures.append(f"{sites_file}: JSON object ではありません")
                    continue
                sites = raw.get("sites", [])
                if not isinstance(sites, list):
                    plan.failures.append(f"{sites_file}: sites が list ではありません")
                    continue
                pdf_size = int(raw.get("pdf_size", 0))
                pdf_mtime = float(raw.get("pdf_mtime", 0.0))
                expected_text_file = paths.facilities_dir / _legacy_name(code, "_facilities", "_text.txt")
                expected_text = expected_text_file.read_text(encoding="utf-8") if expected_text_file.exists() else None
                loaded = load_facilities_cache(land_conn, code, pdf_size=pdf_size, pdf_mtime=pdf_mtime)
                if loaded is None:
                    plan.failures.append(f"{sites_file}: facilities_land に対応行がありません")
                    continue
                loaded_sites, loaded_text = loaded
                if loaded_sites != sites or loaded_text != expected_text:
                    plan.failures.append(f"{sites_file}: facilities_land の内容が一致しません")
                    continue
                plan.add_file(sites_file)
                if expected_text_file.exists():
                    seen_text_files.add(expected_text_file)
                    plan.add_file(expected_text_file)

            for text_file in sorted(paths.facilities_dir.glob("*" + _legacy_name("_facilities", "_text.txt"))):
                if text_file not in seen_text_files:
                    plan.failures.append(f"{text_file}: 対応する *_sites.json が無いため検証できません")

            remaining_children = [
                child
                for child in paths.facilities_dir.iterdir()
                if child not in plan.files_to_delete
            ]
            if not remaining_children:
                plan.add_dir(paths.facilities_dir)
    finally:
        land_conn.close()

    return plan


def _print_cleanup_plan(plan: CleanupPlan, *, dry_run: bool) -> None:
    heading = "cleanup dry-run summary" if dry_run else "cleanup summary"
    print(f"\n=== {heading} ===")
    print(f"  verified file deletions: {len(plan.files_to_delete)}")
    print(f"  verified directory deletions: {len(plan.dirs_to_delete)}")
    print(f"  verification failures: {len(plan.failures)}")
    for path in plan.files_to_delete:
        print(f"  delete file: {path}")
    for path in plan.dirs_to_delete:
        print(f"  delete dir:  {path}")
    for failure in plan.failures:
        print(f"  keep: {failure}")


def _apply_cleanup(plan: CleanupPlan) -> None:
    for path in plan.files_to_delete:
        path.unlink(missing_ok=True)
    for path in plan.dirs_to_delete:
        if path.exists():
            path.rmdir()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate legacy project-owned cache artifacts into land.db")
    parser.add_argument("--cleanup", action="store_true", help="移行後に検証済みの旧構造化キャッシュを削除する")
    parser.add_argument("--dry-run", action="store_true", help="DB・ファイルを変更せずに移行件数と削除予定を表示する")
    return parser.parse_args(argv)


def execute(paths: LegacyPaths, *, cleanup: bool, dry_run: bool) -> int:
    if dry_run:
        tempdir, temp_paths = _create_dry_run_paths(paths)
        try:
            print("=== dry-run: using temporary database copies ===")
            _run_migration(temp_paths)
            if not cleanup:
                return 0
            plan = _plan_cleanup(temp_paths)
            _print_cleanup_plan(plan, dry_run=True)
            return 0 if plan.ok else 1
        finally:
            tempdir.cleanup()

    _run_migration(paths)
    if not cleanup:
        return 0

    plan = _plan_cleanup(paths)
    _print_cleanup_plan(plan, dry_run=False)
    if not plan.ok:
        return 1
    _apply_cleanup(plan)
    print("\ncleanup complete")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return execute(LegacyPaths.defaults(), cleanup=bool(args.cleanup), dry_run=bool(args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
