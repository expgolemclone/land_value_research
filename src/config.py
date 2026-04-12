"""プロジェクト全体のパス定数を一元管理する."""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# config
CONFIG_DIR = PROJECT_ROOT / "config"
ADDRESS_OVERRIDES_PATH = CONFIG_DIR / "address_overrides.yaml"
PRICE_OVERRIDES_PATH = CONFIG_DIR / "price_overrides.yaml"
PATCH_DIR = CONFIG_DIR / "address_patches"
INPUT_CSV = CONFIG_DIR / "input.csv"
INPUT_FULL_CSV = CONFIG_DIR / "input_full.csv"

# data
DATA_DIR = PROJECT_ROOT / "data"
GEOJSON_PATH = DATA_DIR / "landprice" / "merged" / "L01_L02_merged_13.geojson"
OAZA_CSV = DATA_DIR / "geocoding" / "geocode_ref_oaza_chome_tokyo_2024" / "13_2024.csv"
GAIKU_CSV = DATA_DIR / "geocoding" / "geocode_ref_gaiku_tokyo_2024" / "13_2024.csv"

# land.db
LAND_DB_PATH = DATA_DIR / "land.db"

# cache (under data/)
CACHE_DIR = DATA_DIR / "cache"
COMPANY_MASTER_PATH = CACHE_DIR / "company_master.yaml"
PRICE_CACHE_PATH = CACHE_DIR / "price_result_cache.json"
GEOCODE_CACHE_PATH = CACHE_DIR / "geocode_result_cache.json"
MARKET_CAP_CACHE_PATH = CACHE_DIR / "market_cap_cache.json"
PDF_CACHE_DIR = CACHE_DIR / "pdf"
FACILITIES_CACHE_DIR = CACHE_DIR / "facilities_land"
WEB_ADDRESS_CACHE_DIR = CACHE_DIR / "web_address"
ADDR_OVERRIDES_HASH = "addr_overrides_hash.json"
PRICE_OVERRIDES_HASH = "price_overrides_hash.json"

# output
DEFAULT_OUTPUT_DIR = DATA_DIR / "output"
RUN_LOGS_DIR = DEFAULT_OUTPUT_DIR / "run_logs"
DEFAULT_RANKING_PATH = DATA_DIR / "ranking" / "ranking_market_cap_ratio.html"

# rust source (for cache invalidation hashes)
RUST_SRC_DIR = PROJECT_ROOT / "rust_src"
LANDPRICE_RS = RUST_SRC_DIR / "landprice_tokyo.rs"
GEOCODE_RS = RUST_SRC_DIR / "geocode_tokyo.rs"

# magic numbers
MAGIC_NUMBERS_PATH = CONFIG_DIR / "magic_numbers.toml"


def _load_magic_numbers() -> dict[str, dict[str, int | float]]:
    with MAGIC_NUMBERS_PATH.open("rb") as f:
        return tomllib.load(f)  # type: ignore[return-value]


MAGIC: dict[str, dict[str, int | float]] = _load_magic_numbers()
