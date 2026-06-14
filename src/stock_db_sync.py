from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from src.company_store import CompanyDirectory, merge_company_record

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
_DEFAULT_MARKET_CAP_MAX_AGE_DAYS = 7
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_STOCK_DB_ROOT = _PROJECT_ROOT.parent / "stock_db"
JsonValue: TypeAlias = (
    None
    | bool
    | int
    | float
    | str
    | list["JsonValue"]
    | dict[str, "JsonValue"]
)


class PriceRefreshError(RuntimeError):
    """Raised when stock_db cannot refresh stale prices."""


@dataclass(frozen=True)
class StockDbCompanyMetadata:
    company_name: str = ""


@dataclass(frozen=True)
class StockDbXbrlArtifact:
    doc_id: str
    xbrl_path: str
    source_size: int
    source_mtime_ns: int


def _normalize_codes(codes: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_code in codes:
        code = str(raw_code).strip()
        if not code or code in seen:
            continue
        seen.add(code)
        normalized.append(code)
    return normalized


def _reject_db_path(db_path: Path | None) -> None:
    if db_path is not None:
        raise ValueError("stock_db db_path override is no longer supported; use stock_db Rust CLI")


def _is_placeholder_company_name(company_name: str, code: str) -> bool:
    compact_name = _WHITESPACE_RE.sub("", company_name or "")
    return not compact_name or compact_name == code


def load_stock_db_company_metadata(
    codes: Iterable[str],
    *,
    db_path: Path | None = None,
) -> dict[str, StockDbCompanyMetadata]:
    _reject_db_path(db_path)
    normalized_codes = _normalize_codes(codes)
    if not normalized_codes:
        return {}

    names = get_stock_names()
    result: dict[str, StockDbCompanyMetadata] = {}
    for code in normalized_codes:
        company_name = str(names.get(code, "") or "")
        if company_name:
            result[code] = StockDbCompanyMetadata(company_name=company_name)
    return result


def ensure_prices_fresh() -> None:
    result = subprocess.run(
        ["uv", "run", "refresh-prices", "--if-needed", "--headless"],
        cwd=_stock_db_root(),
        env=_stock_db_env(),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        raise PriceRefreshError(message or f"refresh-prices exited {result.returncode}")


def get_stock_names() -> dict[str, str]:
    raw = _expect_dict(_run_stock_db_json(["downstream-stock-names"]))
    return {str(code): str(name) for code, name in raw.items()}


def get_latest_xbrl_artifacts(codes: Iterable[str]) -> dict[str, dict[str, JsonValue]]:
    raw = _expect_dict(
        _run_stock_db_json(
            ["downstream-latest-xbrl-artifacts"],
            tickers=_normalize_codes(codes),
        )
    )
    result: dict[str, dict[str, JsonValue]] = {}
    for code, row in raw.items():
        if not isinstance(row, dict):
            raise ValueError(f"XBRL artifact row must be an object: {code}")
        result[str(code)] = row
    return result


def get_stock_market_caps(
    codes: Iterable[str],
    *,
    max_age_days: int = _DEFAULT_MARKET_CAP_MAX_AGE_DAYS,
) -> dict[str, int]:
    raw = _expect_dict(
        _run_stock_db_json(
            ["downstream-stock-market-caps", "--max-age-days", str(max_age_days)],
            tickers=_normalize_codes(codes),
        )
    )
    return {str(code): int(value) for code, value in raw.items()}


def load_stock_db_xbrl_artifacts(
    codes: Iterable[str],
    *,
    db_path: Path | None = None,
) -> dict[str, StockDbXbrlArtifact]:
    _reject_db_path(db_path)
    normalized_codes = _normalize_codes(codes)
    if not normalized_codes:
        return {}

    rows = get_latest_xbrl_artifacts(normalized_codes)
    result: dict[str, StockDbXbrlArtifact] = {}
    for code, row in rows.items():
        result[code] = StockDbXbrlArtifact(
            doc_id=str(row["doc_id"]),
            xbrl_path=str(row["xbrl_path"]),
            source_size=int(row["source_size"]),
            source_mtime_ns=int(row["source_mtime_ns"]),
        )
    return result


def load_market_cap_from_stock_db(
    codes: Iterable[str],
    *,
    db_path: Path | None = None,
    max_age_days: int = _DEFAULT_MARKET_CAP_MAX_AGE_DAYS,
) -> dict[str, int]:
    _reject_db_path(db_path)
    normalized_codes = _normalize_codes(codes)
    if not normalized_codes:
        return {}
    return get_stock_market_caps(normalized_codes, max_age_days=max_age_days)


def refresh_stock_prices() -> bool:
    """Ask stock_db Rust CLI to refresh stale prices if needed."""

    logger.info("stock_db 株価更新開始")
    try:
        ensure_prices_fresh()
    except (PriceRefreshError, ValueError) as exc:
        logger.warning("stock_db 株価更新失敗: %s", exc)
        return False

    logger.info("stock_db 株価更新完了")
    return True


def _stock_db_root() -> Path:
    configured = os.environ.get("STOCK_DB_ROOT")
    root = Path(configured).expanduser() if configured else _DEFAULT_STOCK_DB_ROOT
    if not root.is_dir():
        raise ValueError(f"stock_db root does not exist: {root}")
    return root


def _stock_db_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("STOCK_DB_ROOT", str(_stock_db_root()))
    return env


def _run_stock_db_json(
    args: list[str],
    *,
    tickers: list[str] | None = None,
) -> JsonValue:
    input_text = None if tickers is None else json.dumps(tickers)
    result = subprocess.run(
        ["cargo", "run", "-q", "-p", "edinet-xbrl", "--", *args],
        cwd=_stock_db_root(),
        env=_stock_db_env(),
        input=input_text,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        raise ValueError(message or f"edinet-xbrl {' '.join(args)} exited {result.returncode}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"edinet-xbrl {' '.join(args)} emitted invalid JSON") from exc


def _expect_dict(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object, got {type(value).__name__}")
    return value


def sync_company_records_from_stock_db(
    company_records: CompanyDirectory,
    codes: Iterable[str],
    *,
    conn: sqlite3.Connection | None = None,
    db_path: Path | None = None,
) -> int:
    metadata_by_code = load_stock_db_company_metadata(codes, db_path=db_path)
    updated = 0

    for code, metadata in metadata_by_code.items():
        current = company_records.get(code, {})
        next_values: dict[str, str] = {}

        current_name = str(current.get("company_name", "") or "")
        if metadata.company_name and _is_placeholder_company_name(current_name, code):
            next_values["company_name"] = metadata.company_name

        if not next_values:
            continue

        if conn is not None:
            company_records[code] = merge_company_record(conn, code, **next_values)
        else:
            merged = dict(current)
            merged.update(next_values)
            company_records[code] = merged
        updated += 1

    return updated
