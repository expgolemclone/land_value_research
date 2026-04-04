# ruff: noqa: E402
"""Pre-check tool for split-address parallel execution.

Called by parallel_research.py before each process launch.
Reads the output CSV for a given company and produces a JSON summary of
risk flags and geocode levels to save context.

Usage:
    uv run python scripts/_codex_precheck.py <証券コード>
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import yaml

from src.schema import (
    COL_ADDRESS,
    COL_ADDRESS_SOURCE,
    COL_ANOMALY_WARNING,
    COL_GEOCODE_LEVEL,
    COL_LAND_AREA,
    COL_SITE_NAME,
)

from src.config import ADDRESS_OVERRIDES_PATH, DEFAULT_OUTPUT_DIR

OVERRIDES_FILE = ADDRESS_OVERRIDES_PATH
DOCS_DIR = PROJECT_ROOT / "split-address"
OUTPUT_DIR = DEFAULT_OUTPUT_DIR

# High-price wards where large area is suspicious (BAD_PATTERN_1)
HIGH_PRICE_WARDS = {
    "千代田区",
    "中央区",
    "港区",
    "新宿区",
    "渋谷区",
    "文京区",
    "台東区",
    "豊島区",
    "目黒区",
    "品川区",
}

AREA_THRESHOLD_M2 = 10_000.0


def _is_aggregate_site_name(site_name: str) -> bool:
    """Replicate anomaly.is_aggregate_site_name without importing the module."""
    normalized = re.sub(r"\s+", "", (site_name or ""))
    if not normalized:
        return False
    if "本社他" in normalized or normalized.startswith("本社・"):
        return True
    return normalized.endswith("他") or normalized.endswith("等")


def _has_multi_location_signal(site_name: str) -> bool:
    """Check for multi-location signal keywords (broader than aggregate check)."""
    normalized = re.sub(r"\s+", "", (site_name or ""))
    return bool(re.search(r"他|ほか|及び|等|外", normalized))


def _extract_ward(address: str) -> str | None:
    """Extract ward name (e.g. '港区') from a Tokyo address."""
    m = re.search(r"東京都(\S+?[区市町村])", address or "")
    return m.group(1) if m else None


def _load_overrides() -> dict[str, dict]:
    if not OVERRIDES_FILE.exists():
        return {}
    with open(OVERRIDES_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items()}


def precheck(code: str) -> dict:
    csv_path = OUTPUT_DIR / f"{code}_output.csv"
    docs_exists = (DOCS_DIR / f"{code}.md").exists()

    if not csv_path.exists():
        return {
            "code": code,
            "error": f"CSV not found: {csv_path}",
            "sites": [],
            "all_gaiku": False,
            "has_risk": False,
            "docs_exists": docs_exists,
        }

    overrides = _load_overrides()
    company_overrides = overrides.get(code, {})
    has_override_for_company = isinstance(company_overrides, dict) and len(company_overrides) > 0

    sites = []
    all_gaiku = True
    has_risk = False

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            site_name = row.get(COL_SITE_NAME, "")
            # Skip aggregate summary row
            if site_name == "東京都合計":
                continue

            geocode_level = row.get(COL_GEOCODE_LEVEL, "")
            address = row.get(COL_ADDRESS, "")
            address_source = row.get(COL_ADDRESS_SOURCE, "")
            anomaly_warning = row.get(COL_ANOMALY_WARNING, "")

            try:
                area_m2 = float(row.get(COL_LAND_AREA, "0"))
            except (ValueError, TypeError):
                area_m2 = 0.0

            is_hoka = _has_multi_location_signal(site_name)
            is_aggregate = _is_aggregate_site_name(site_name)
            ward = _extract_ward(address)
            is_high_price_ward = ward in HIGH_PRICE_WARDS if ward else False
            has_override = site_name in company_overrides if has_override_for_company else False

            # BAD_PATTERN_1 risk: aggregate name OR (large area in high-price ward)
            bad_pattern_1_risk = is_aggregate or (area_m2 >= AREA_THRESHOLD_M2 and is_high_price_ward)

            # Multi-location anomaly from pipeline
            has_multi_loc_warning = "複数所在地シグナル" in anomaly_warning

            if geocode_level != "gaiku":
                all_gaiku = False

            if bad_pattern_1_risk or geocode_level != "gaiku" or has_multi_loc_warning:
                has_risk = True

            sites.append(
                {
                    "site_name": site_name,
                    "geocode_level": geocode_level,
                    "address_source": address_source,
                    "has_hoka": is_hoka,
                    "is_aggregate": is_aggregate,
                    "area_m2": area_m2,
                    "ward": ward,
                    "has_override": has_override,
                    "bad_pattern_1_risk": bad_pattern_1_risk,
                    "has_multi_loc_warning": has_multi_loc_warning,
                }
            )

    return {
        "code": code,
        "sites": sites,
        "all_gaiku": all_gaiku,
        "has_risk": has_risk,
        "docs_exists": docs_exists,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: uv run python scripts/_codex_precheck.py <証券コード>", file=sys.stderr)
        return 2

    code = argv[1]
    result = precheck(code)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
