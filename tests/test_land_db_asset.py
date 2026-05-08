from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.land_db.asset import LandDbDownloadError, ensure_land_db_exists
from src.land_db.schema import init_land_db


def _create_source_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        init_land_db(conn)
        conn.commit()
    finally:
        conn.close()


def test_downloads_land_db_from_asset_url(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    dest = tmp_path / "land.db"
    _create_source_db(source)

    result = ensure_land_db_exists(
        dest,
        asset_url=source.as_uri(),
        allow_gh_fallback=False,
    )

    assert result == dest
    conn = sqlite3.connect(dest)
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'company_metadata'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None


def test_missing_asset_raises_without_creating_land_db(tmp_path: Path) -> None:
    dest = tmp_path / "land.db"
    missing = tmp_path / "missing.db"

    with pytest.raises(LandDbDownloadError):
        ensure_land_db_exists(
            dest,
            asset_url=missing.as_uri(),
            allow_gh_fallback=False,
        )

    assert not dest.exists()


def test_missing_asset_removes_empty_land_db(tmp_path: Path) -> None:
    dest = tmp_path / "land.db"
    missing = tmp_path / "missing.db"
    dest.write_bytes(b"")

    with pytest.raises(LandDbDownloadError):
        ensure_land_db_exists(
            dest,
            asset_url=missing.as_uri(),
            allow_gh_fallback=False,
        )

    assert not dest.exists()
