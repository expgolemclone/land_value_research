from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from typing import Any

from src.pdf_extract import FacilityLand

logger = logging.getLogger(__name__)


def file_md5(path: str) -> str:
    """ファイルの MD5 ハッシュを返す."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def combined_md5(*paths: str) -> str:
    """複数ファイルの MD5 を結合して単一ハッシュを生成."""
    h = hashlib.md5()
    for p in sorted(paths):
        h.update(file_md5(p).encode())
    return h.hexdigest()


def string_md5(s: str) -> str:
    """文字列の MD5 ハッシュを返す（キャッシュキー用）."""
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _atomic_json_write(path: str, obj: object) -> None:
    dir_name = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_json_dict(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d
    except Exception:
        logger.debug("json dict load failed: %s", path, exc_info=True)
    return {}


def save_json_dict(path: str, d: dict[str, Any]) -> None:
    _atomic_json_write(path, d)


def load_sites_cache(cache_path: str, pdf_path: str) -> list[FacilityLand] | None:
    if not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, encoding="utf-8") as f:
            d = json.load(f)
        stat = os.stat(pdf_path)
        if (
            d.get("cache_version") != 5
            or int(d.get("pdf_size", -1)) != int(stat.st_size)
            or str(d.get("pdf_mtime", "")) != str(stat.st_mtime)
        ):
            return None
        out: list[FacilityLand] = []
        for x in d.get("sites", []):
            out.append(
                FacilityLand(
                    site_name=str(x.get("site_name", "")),
                    location_short=str(x.get("location_short", "")),
                    land_area_m2=float(x.get("land_area_m2", 0.0)),
                    land_book_value_yen=float(x.get("land_book_value_yen", 0.0)),
                    location_has_hoka=bool(x.get("location_has_hoka", False)),
                    equipment_type=str(x.get("equipment_type", "")),
                )
            )
        return out
    except Exception:
        logger.debug("sites cache load failed: %s", cache_path, exc_info=True)
        return None


def save_sites_cache(cache_path: str, pdf_path: str, sites: list[FacilityLand]) -> None:
    stat = os.stat(pdf_path)
    payload = {
        "cache_version": 5,
        "pdf_size": int(stat.st_size),
        "pdf_mtime": float(stat.st_mtime),
        "sites": [
            {
                "site_name": s.site_name,
                "location_short": s.location_short,
                "land_area_m2": float(s.land_area_m2),
                "land_book_value_yen": float(s.land_book_value_yen),
                "location_has_hoka": s.location_has_hoka,
                "equipment_type": s.equipment_type,
            }
            for s in sites
        ],
    }
    _atomic_json_write(cache_path, payload)
