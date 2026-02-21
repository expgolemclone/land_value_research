from __future__ import annotations

import csv
import os
from typing import Any

import yaml


def load_company_master(path: str) -> dict[str, dict[str, Any]]:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    # key: str code
    return {str(k): v for k, v in data.items()}


def load_address_overrides(path: str) -> dict[str, dict[str, str]]:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    out: dict[str, dict[str, str]] = {}
    for code, mapping in data.items():
        out[str(code)] = {str(k): str(v) for k, v in (mapping or {}).items()}
    return out


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
            out[code] = float(val)
    return out
