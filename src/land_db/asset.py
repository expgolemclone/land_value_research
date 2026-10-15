from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sqlite3
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from src.config import (
    LAND_DB_ASSET_NAME,
    LAND_DB_ASSET_SHA256,
    LAND_DB_ASSET_URL,
    LAND_DB_PATH,
    LAND_DB_RELEASE_REPO,
    LAND_DB_RELEASE_TAG,
)

logger = logging.getLogger(__name__)


class LandDbDownloadError(RuntimeError):
    """land.db の取得に失敗した."""


def ensure_land_db_exists(
    db_path: Path = LAND_DB_PATH,
    *,
    asset_url: str | None = None,
    expected_sha256: str | None = None,
    allow_gh_fallback: bool = True,
) -> Path:
    """既定の land.db が無ければ Release asset から取得する.

    空の SQLite DB を作らないため、呼び出し側が sqlite3 で開く前に必ず実行する。
    """
    if db_path.exists() and db_path.stat().st_size > 0:
        return db_path

    return download_land_db(
        db_path=db_path,
        asset_url=asset_url,
        expected_sha256=expected_sha256,
        allow_gh_fallback=allow_gh_fallback,
        force=True,
    )


def download_land_db(
    db_path: Path = LAND_DB_PATH,
    *,
    asset_url: str | None = None,
    expected_sha256: str | None = None,
    allow_gh_fallback: bool = True,
    force: bool = False,
) -> Path:
    """GitHub Release asset から land.db をダウンロードして配置する."""
    if db_path.exists() and db_path.stat().st_size > 0 and not force:
        return db_path

    url = asset_url if asset_url is not None else LAND_DB_ASSET_URL
    sha256 = expected_sha256 if expected_sha256 is not None else LAND_DB_ASSET_SHA256
    remove_empty_db_on_failure = db_path.exists() and db_path.stat().st_size == 0
    db_path.parent.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    try:
        _download_with_url(url, db_path, sha256)
        return db_path
    except LandDbDownloadError as exc:
        failures.append(str(exc))

    if allow_gh_fallback:
        try:
            _download_with_gh(db_path, sha256)
            return db_path
        except LandDbDownloadError as exc:
            failures.append(str(exc))

    detail = "\n".join(f"- {failure}" for failure in failures)
    if remove_empty_db_on_failure:
        _remove_tmp(db_path)
    raise LandDbDownloadError(
        f"{db_path} が存在しないため GitHub Release asset から取得しましたが失敗しました。\n"
        f"asset 名は {LAND_DB_ASSET_NAME}、URL は {url} です。\n"
        f"{detail}"
    )


def _download_with_url(url: str, db_path: Path, expected_sha256: str) -> None:
    tmp_path = db_path.parent / f".{db_path.name}.download"
    try:
        headers = {"User-Agent": "land-value-research/0.1"}
        token = os.environ.get("LAND_DB_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if token and "github.com/" in url:
            headers["Authorization"] = f"Bearer {token}"

        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=60) as response:
            with tmp_path.open("wb") as f:
                shutil.copyfileobj(response, f)

        _validate_download(tmp_path, expected_sha256)
        os.replace(tmp_path, db_path)
    except (OSError, sqlite3.Error, urllib.error.URLError, ValueError) as exc:
        _remove_tmp(tmp_path)
        raise LandDbDownloadError(f"URL ダウンロード失敗: {exc}") from exc


def _download_with_gh(db_path: Path, expected_sha256: str) -> None:
    try:
        with tempfile.TemporaryDirectory(prefix="land-db-asset-", dir=str(db_path.parent)) as tmpdir:
            tmp_dir = Path(tmpdir)
            cmd = ["gh", "release", "download"]
            if LAND_DB_RELEASE_TAG != "latest":
                cmd.append(LAND_DB_RELEASE_TAG)
            cmd.extend(
                [
                    "--repo",
                    LAND_DB_RELEASE_REPO,
                    "--pattern",
                    LAND_DB_ASSET_NAME,
                    "--dir",
                    str(tmp_dir),
                    "--clobber",
                ]
            )
            result = subprocess.run(cmd, capture_output=True, check=False, text=True)
            if result.returncode != 0:
                message = (result.stderr or result.stdout or "").strip()
                raise LandDbDownloadError(f"gh release download 失敗: {message or result.returncode}")

            downloaded = tmp_dir / LAND_DB_ASSET_NAME
            if not downloaded.exists():
                raise LandDbDownloadError(f"gh release download が {LAND_DB_ASSET_NAME} を出力しませんでした")

            _validate_download(downloaded, expected_sha256)
            os.replace(downloaded, db_path)
    except FileNotFoundError as exc:
        raise LandDbDownloadError("gh コマンドが見つかりません") from exc
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise LandDbDownloadError(f"gh ダウンロード失敗: {exc}") from exc


def _validate_download(db_path: Path, expected_sha256: str) -> None:
    if not db_path.exists() or db_path.stat().st_size == 0:
        raise ValueError("downloaded land.db is empty")

    if expected_sha256:
        actual = _sha256(db_path)
        if actual.lower() != expected_sha256.lower():
            raise ValueError(f"sha256 mismatch: expected {expected_sha256}, got {actual}")

    conn = sqlite3.connect(str(db_path))
    try:
        quick_check = conn.execute("PRAGMA quick_check").fetchone()
        if quick_check is None or str(quick_check[0]).lower() != "ok":
            raise ValueError(f"sqlite quick_check failed: {quick_check}")
    finally:
        conn.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_tmp(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("一時ファイルの削除に失敗しました: %s", path)
