# TREE

run.py [1223L] -> rank_market_cap_ratio, scripts.merge_address_patches, src.*
rank_market_cap_ratio.py [568L] -> src.company_config, src.company_metadata_fallback, src.schema
src/
  schema.py [121L] (SSOT: OUTPUT_COLUMNS, RANKING_COLUMNS, COL_* constants)
  utils.py [23L] (ensure_dir, validate_url_not_private)
  cache.py [93L] -> src.pdf_extract
  network.py [53L] (is_transient_network_error, urlopen_with_retry)
  web_cache.py [30L] -> src.network, src.utils
  jp_address.py [178L] (normalize_addr, split_tokyo_municipality, parse_town_chome_block)
  landprice_tokyo.py [3L] re-export land_value_core{LandPriceTokyo, PriceResult}
  geocode_tokyo.py [3L] re-export land_value_core{TokyoGeocoder}
  pdf_extract.py [450L] (FacilityLand, extract_major_facilities_land, extract_facilities_section_text)
  anomaly.py [132L] -> src.landprice_tokyo, src.schema
  company_config.py [201L] -> src.pdf_extract
  company_metadata_fallback.py [113L] -> src.network, src.utils
  web_address_research.py [328L] -> src.jp_address, src.network, src.utils
rust_src/ (PyO3 module: land_value_core)
  lib.rs [36L] registers {PriceResult, LandPriceTokyo, TokyoGeocoder}
  types.rs [35L] struct PriceResult
  coord.rs [85L] (lonlat_to_plane, ellipsoid_distance, ellipsoid_distances)
  landprice_tokyo.rs [556L] -> coord, types
  geocode_tokyo.rs [341L] -> jp_address
  jp_address.rs [321L] (normalize_addr, split_tokyo_municipality, parse_town_chome_block)
scripts/
  parallel_research.py [935L] -> scripts._codex_precheck, scripts.codex_lockdown
  merge_address_patches.py [220L] (merge_patches_safe; マージ時に影響企業のoutput CSVを削除)
  merge_landprice.py [97L] standalone GeoJSON merge
  populate_company_master.py [184L] -> src.company_config, src.network
  populate_company_names.py [108L] -> src.company_config
  codex_lockdown.py [252L] standalone permission lockdown
  validate_ocr_accuracy.py [183L] -> src.pdf_extract
  loop_runner.py [87L] standalone subprocess launcher
  _codex_precheck.py [182L] standalone CSV/JSON checker
  _codex_geocode_check.py [33L] -> src.geocode_tokyo
config/
  company_master.yaml
  address_overrides.yaml
  address_patches/*.precheck.json
  input.csv, input_full.csv
data/
  landprice/merged/ (GeoJSON)
  geocoding/geocode_ref_gaiku_tokyo_2024/ (CSV)
  cache/ {price_result_cache.json, geocode_result_cache.json, addr_overrides_hash.json}
  cache/pdf/ {code}_securities_report.pdf
  cache/facilities_land/ {code}_sites.json
  cache/web_address/
  output/ {code}_output.csv
  ranking/ ranking_market_cap_ratio.html

# SYMBOLS

class LandPriceTokyo @rust_src/landprice_tokyo.rs:22 <-src/landprice_tokyo.py, run.py
class TokyoGeocoder @rust_src/geocode_tokyo.rs:47 <-src/geocode_tokyo.py, run.py, scripts/_codex_geocode_check.py
struct PriceResult @rust_src/types.rs:6 <-src/landprice_tokyo.py, src/anomaly.py, run.py
class FacilityLand @src/pdf_extract.py:13 <-src/cache.py, src/company_config.py, run.py
class SiteSplitEntry @src/company_config.py:16 <-run.py
class WebAddressResearcher @src/web_address_research.py:35 <-run.py
class CompanyMetadata @src/company_metadata_fallback.py:16 <-run.py, rank_market_cap_ratio.py
class OutputRow @src/schema.py:51 <-src/anomaly.py, run.py
fn extract_major_facilities_land @src/pdf_extract.py:372 <-run.py, scripts/validate_ocr_accuracy.py
fn calc_uncertainty_metrics @src/anomaly.py:21 <-run.py
fn detect_anomaly_warnings @src/anomaly.py:42 <-run.py
fn detect_duplicate_address_large_area @src/anomaly.py:94 <-run.py
fn should_accept_web_address @src/anomaly.py:72 <-run.py
fn load_company_master @src/company_config.py:29 <-run.py, rank_market_cap_ratio.py, scripts/populate_company_master.py, scripts/populate_company_names.py
fn save_company_master @src/company_config.py:197 <-run.py, rank_market_cap_ratio.py, scripts/populate_company_names.py
fn load_address_overrides @src/company_config.py:40 <-run.py
fn expand_site_splits @src/company_config.py:105 <-run.py
fn fetch_from_irbank @src/company_metadata_fallback.py:54 <-run.py, rank_market_cap_ratio.py
fn load_json_dict @src/cache.py:29 <-run.py
fn save_json_dict @src/cache.py:42 <-run.py
fn load_sites_cache @src/cache.py:46 <-run.py
fn save_sites_cache @src/cache.py:76 <-run.py
fn is_transient_network_error @src/network.py:14 <-run.py
fn urlopen_with_retry @src/network.py:37 <-src/company_metadata_fallback.py, src/web_address_research.py, src/web_cache.py, scripts/populate_company_master.py
fn validate_url_not_private @src/utils.py:10 <-src/company_metadata_fallback.py, src/web_address_research.py, src/web_cache.py
fn normalize_addr @src/jp_address.py:42 <-src/web_address_research.py
fn split_tokyo_municipality @src/jp_address.py:120 <-src/web_address_research.py
fn merge_patches_safe @scripts/merge_address_patches.py:51 <-run.py
fn generate_ranking @rank_market_cap_ratio.py:524 <-run.py
fn download_file @src/web_cache.py:19 <-run.py
fn is_pdf_file @src/web_cache.py:10 <-run.py
const OUTPUT_COLUMNS @src/schema.py:17 <-run.py
const RANKING_COLUMNS @src/schema.py:56 <-rank_market_cap_ratio.py

# GRAPH

run.py -> {rank_market_cap_ratio, scripts.merge_address_patches, src.anomaly, src.cache, src.company_config, src.company_metadata_fallback, src.geocode_tokyo, src.landprice_tokyo, src.network, src.pdf_extract, src.schema, src.utils, src.web_address_research, src.web_cache}
rank_market_cap_ratio.py -> {src.company_config, src.company_metadata_fallback, src.schema}
src.anomaly -> {src.landprice_tokyo, src.schema}
src.cache -> {src.pdf_extract}
src.company_config -> {src.pdf_extract}
src.company_metadata_fallback -> {src.network, src.utils}
src.web_address_research -> {src.jp_address, src.network, src.utils}
src.web_cache -> {src.network, src.utils}
src.landprice_tokyo -> land_value_core (Rust)
src.geocode_tokyo -> land_value_core (Rust)
land_value_core: landprice_tokyo -> {coord, types}; geocode_tokyo -> {jp_address}
scripts.parallel_research -> {scripts._codex_precheck, scripts.codex_lockdown}
scripts.populate_company_master -> {src.company_config, src.network}
scripts.populate_company_names -> {src.company_config}
scripts.validate_ocr_accuracy -> {src.pdf_extract}
scripts._codex_geocode_check -> {src.geocode_tokyo}

# CACHE

price_result_cache.json invalidated by MD5(data/landprice/merged/*.geojson + rust_src/landprice_tokyo.rs)
geocode_result_cache.json invalidated by MD5(data/geocoding/**/*.csv + rust_src/geocode_tokyo.rs)
facilities_land/{code}_sites.json invalidated by PDF stat(size+mtime) + cache_version
addr_overrides_hash.json invalidated by MD5(address_overrides.yaml per-company); triggers delete output/{code}_output.csv
market_cap_cache.json: external API, daily refresh (no auto-invalidation)
web_address/: external web results, volatile (no auto-invalidation)
