"""プロジェクト全体のパス定数を一元管理する."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

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
LAND_DB_ASSET_NAME = "land.db"
LAND_DB_RELEASE_REPO = os.environ.get("LAND_DB_RELEASE_REPO", "expgolemclone/land_value_research")
LAND_DB_RELEASE_TAG = os.environ.get("LAND_DB_RELEASE_TAG", "latest")


def _default_land_db_asset_url() -> str:
    if LAND_DB_RELEASE_TAG == "latest":
        return f"https://github.com/{LAND_DB_RELEASE_REPO}/releases/latest/download/{LAND_DB_ASSET_NAME}"
    return f"https://github.com/{LAND_DB_RELEASE_REPO}/releases/download/{LAND_DB_RELEASE_TAG}/{LAND_DB_ASSET_NAME}"


LAND_DB_ASSET_URL = os.environ.get("LAND_DB_ASSET_URL", _default_land_db_asset_url())
LAND_DB_ASSET_SHA256 = os.environ.get("LAND_DB_ASSET_SHA256", "")

# cache (under data/)
CACHE_DIR = DATA_DIR / "cache"
PDF_CACHE_DIR = CACHE_DIR / "pdf"
WEB_ADDRESS_CACHE_DIR = CACHE_DIR / "web_address"

# output
DEFAULT_OUTPUT_DIR = DATA_DIR / "output"
RUN_LOGS_DIR = DEFAULT_OUTPUT_DIR / "run_logs"

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
