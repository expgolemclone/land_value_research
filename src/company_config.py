from __future__ import annotations

import csv
import logging
import os
from dataclasses import dataclass
from typing import Any

import yaml

from src.pdf_extract import FacilityLand

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SiteSplitEntry:
    """address_overrides.yaml のサイト分割エントリ1件."""

    name: str
    address: str
    area_m2: float
    book_value_yen: float | None = None  # None = 面積比按分


def load_company_master(path: str) -> dict[str, dict[str, Any]]:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    # key: str code
    return {str(k): v for k, v in data.items()}


def load_address_overrides(path: str) -> dict[str, dict[str, str | list[SiteSplitEntry]]]:
    """address_overrides.yaml をロードする.

    値が文字列の場合は住所上書き(既存動作)、リストの場合はサイト分割エントリとして解釈する。
    """
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, str | list[SiteSplitEntry]]] = {}
    for code, mapping in data.items():
        if not isinstance(mapping, dict):
            continue
        entries: dict[str, str | list[SiteSplitEntry]] = {}
        for k, v in mapping.items():
            if isinstance(v, list):
                entries[str(k)] = _parse_split_entries(str(code), str(k), v)
            else:
                entries[str(k)] = str(v)
        out[str(code)] = entries
    return out


def _parse_split_entries(code: str, site_name: str, raw_list: list) -> list[SiteSplitEntry]:
    """YAMLリスト形式の分割エントリをパースする."""
    if not raw_list:
        raise ValueError(f"サイト分割エントリが空です: {code} / {site_name}")
    result: list[SiteSplitEntry] = []
    for i, item in enumerate(raw_list):
        if not isinstance(item, dict):
            raise ValueError(f"サイト分割エントリが辞書ではありません: {code} / {site_name}[{i}]: {item}")
        missing = [f for f in ("name", "address", "area_m2") if f not in item]
        if missing:
            raise ValueError(
                f"サイト分割エントリに必須フィールドがありません: {code} / {site_name}[{i}]: {', '.join(missing)}"
            )
        result.append(
            SiteSplitEntry(
                name=str(item["name"]),
                address=str(item["address"]),
                area_m2=float(item["area_m2"]),
                book_value_yen=float(item["book_value_yen"]) if "book_value_yen" in item else None,
            )
        )
    return result


def expand_site_splits(
    sites: list[FacilityLand],
    overrides: dict[str, str | list[SiteSplitEntry]],
) -> tuple[list[FacilityLand], dict[str, str]]:
    """分割指定されたサイトを展開し、展開後のサイトリストとフラットな override dict を返す.

    Args:
        sites: PDF抽出された FacilityLand リスト
        overrides: 該当企業の address_overrides (str or list[SiteSplitEntry])

    Returns:
        expanded_sites: 展開後の FacilityLand リスト
        flat_overrides: 全エントリが str のみの override dict (_process_site 用)
    """
    flat_overrides: dict[str, str] = {}
    split_map: dict[str, list[SiteSplitEntry]] = {}

    for site_name, value in overrides.items():
        if isinstance(value, list):
            split_map[site_name] = value
            for entry in value:
                flat_overrides[entry.name] = entry.address
        else:
            flat_overrides[site_name] = value

    if not split_map:
        return sites, flat_overrides

    expanded: list[FacilityLand] = []
    for s in sites:
        if s.site_name in split_map:
            split_entries = split_map[s.site_name]
            allocated = _allocate_book_values(s, split_entries)
            for entry in allocated:
                expanded.append(
                    FacilityLand(
                        site_name=entry.name,
                        location_short=entry.address,
                        land_area_m2=entry.area_m2,
                        land_book_value_yen=entry.book_value_yen,
                    )
                )
        else:
            expanded.append(s)

    return expanded, flat_overrides


def _allocate_book_values(
    original: FacilityLand,
    entries: list[SiteSplitEntry],
) -> list[SiteSplitEntry]:
    """book_value_yen が None のエントリに面積比按分で簿価を割り当てる."""
    if all(e.book_value_yen is not None for e in entries):
        return entries

    specified_total = sum(e.book_value_yen for e in entries if e.book_value_yen is not None)
    remaining_book = original.land_book_value_yen - specified_total

    unspecified_area_total = sum(e.area_m2 for e in entries if e.book_value_yen is None)

    result: list[SiteSplitEntry] = []
    for e in entries:
        if e.book_value_yen is not None:
            result.append(e)
        else:
            if unspecified_area_total > 0:
                allocated = remaining_book * (e.area_m2 / unspecified_area_total)
            else:
                allocated = 0.0
            result.append(
                SiteSplitEntry(
                    name=e.name,
                    address=e.address,
                    area_m2=e.area_m2,
                    book_value_yen=allocated,
                )
            )
    return result


def save_company_master(path: str, data: dict[str, dict[str, Any]]) -> None:
    """company_master.yaml に証券コード昇順で保存する."""
    sorted_data = dict(sorted(data.items(), key=lambda x: x[0]))
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(sorted_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def load_market_caps(path: str) -> dict[str, float]:
    """時価総額(円). CSV: code,market_cap_yen"""
    if not os.path.exists(path):
        return {}
    out: dict[str, float] = {}
    with open(path, encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            code = str(row.get("code", "")).strip()
            if not code:
                continue
            val = str(row.get("market_cap_yen", "")).replace(",", "").strip()
            if not val:
                continue
            try:
                out[code] = float(val)
            except ValueError:
                continue
    return out
