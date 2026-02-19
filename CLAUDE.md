# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Tool that estimates land values of Tokyo-based assets held by Japanese listed companies. It extracts land holdings from securities reports (有価証券報告書), geocodes addresses, estimates land prices via inverse distance weighting (IDW), and ranks companies by land-value-to-market-cap ratio. All documentation and config files are in Japanese.

## Commands

```bash
# Install
pip install -r requirements.txt
pip install -r requirements-dev.txt   # adds ruff

# Run main pipeline
python run.py

# Generate rankings from output CSVs
python rank_market_cap_ratio.py

# Lint & format
ruff check .
ruff format .

# Tests
python -m pytest tests/ -v
python -m pytest tests/test_geocode_tokyo.py -v   # single file
```

## Code Style

- Ruff: line-length 120, target Python 3.10, rules E/F/W/I/UP
- `tests/` files exempt from E501
- `data/` directory excluded from linting

## Architecture

**Entry points:** `run.py` (main pipeline), `rank_market_cap_ratio.py` (ranking generation)

**Processing pipeline per company (in `run.py`):**
1. **Metadata** — `company_config.py` loads from YAML/CSV; `company_metadata_fallback.py` fills gaps from IRBank
2. **PDF extraction** — `pdf_extract.py` extracts facility tables → `FacilityLand` dataclass (site name, location, area, book value)
3. **Address resolution** (3-tier priority): override YAML → web scraping (score ≥ 40) → securities report as-is
4. **Geocoding** — `geocode_tokyo.py` converts address → (lat, lon, level). Three resolution levels with correction factors: `gaiku` (1.00) → `oaza_chome` (0.95) → `muni_centroid` (0.85)
5. **Price estimation** — `landprice_tokyo.py` uses IDW (k=3, p=3) or nearest-neighbor against ~3000 public land price points
6. **Anomaly detection** — Critical anomalies exclude the company entirely; warnings flag in output only
7. **Output** — Per-company CSV with 33 columns + aggregated "東京都合計" summary row

**Module dependency graph:**
```
run.py
├── pdf_extract.py          # Securities report table extraction
├── geocode_tokyo.py        # Address → coordinates
│   └── jp_address.py       # Japanese address normalization
├── landprice_tokyo.py      # IDW/nearest price estimation
├── web_address_research.py # Web scraping for detailed addresses
│   └── jp_address.py
├── web_cache.py            # PDF download & validation
├── company_config.py       # YAML/CSV config loading
├── company_metadata_fallback.py  # IRBank API fallback
└── utils.py

rank_market_cap_ratio.py
└── company_config.py
```

**Key data structures:**
- `FacilityLand` (frozen dataclass in `pdf_extract.py`) — site_name, location_short, land_area_m2, land_book_value_yen
- `PriceResult` (frozen dataclass in `landprice_tokyo.py`) — unit_price, nearest_id, nearest_dist_m, knn_ids, knn_dist_m, knn_prices
- `CompanyResult` (dataclass in `run.py`) — aggregates output rows, excluded rows, totals per company

**Caching:** JSON disk caches for geocode results, price results, and web address lookups. Saved every 10 companies. PDF facility cache validated by file size + mtime. Clear `data/cache/*.json` if results seem wrong.

## Key Directories

- `config/` — `company_master.yaml`, `address_overrides.yaml`, `market_cap_overrides.csv`
- `data/geocoding/` — Address reference CSVs (oaza_chome, gaiku levels)
- `data/landprice/tokyo_2025/` — Public land price GeoJSON (L01-25_13.geojson)
- `data/cache/` — PDF, web scraping, and facility extraction caches
- `data/output/` — Per-company CSVs, anomaly exclusions, ranking markdowns
