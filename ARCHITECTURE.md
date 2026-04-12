# TREE

run.py [1415L] -> src.rank_market_cap_ratio, scripts.merge_address_patches, src.*, src.browser, src.stealth
browser_service/
  server.js (Node.js Express + puppeteer-real-browser: /fetch, /download, /shutdown)
  package.json, package-lock.json
src/
  rank_market_cap_ratio.py [592L] -> src.company_config, src.company_metadata_fallback, src.schema, src.browser
  config.py [60L] (SSOT: PROJECT_ROOT, CONFIG_DIR, DATA_DIR, CACHE_DIR, 全パス定数, MAGIC)
  schema.py [121L] (SSOT: OUTPUT_COLUMNS, RANKING_COLUMNS, COL_* constants)
  utils.py [23L] (ensure_dir, validate_url_not_private)
  cache.py [118L] -> src.pdf_extract (file_md5, combined_md5, string_md5)
  browser.py [300L] -> src.config (BrowserService: Node.js puppeteer-real-browser クライアント, pty 起動)
  stealth.py [157L] -> src.config (ProxyPool, random_delay)
  network.py [47L] (is_transient_network_error, urlopen_with_retry)
  web_cache.py [50L] -> src.browser, src.utils
  jp_address.py [17L] re-export land_value_core{normalize_addr, split_tokyo_municipality, parse_town_chome_block, num_to_kanji, build_oaza_chome_name, kanji_to_int}
  landprice_tokyo.py [3L] re-export land_value_core{LandPriceTokyo, PriceResult}
  geocode_tokyo.py [3L] re-export land_value_core{TokyoGeocoder}
  pdf_extract.py [522L] (FacilityLand, extract_major_facilities_land, extract_facilities_section_text, batch_extract_facilities)
  anomaly.py [141L] -> src.landprice_tokyo, src.schema
  company_config.py [240L] -> src.pdf_extract
  company_metadata_fallback.py [140L] -> src.browser, src.utils
  web_address_research.py [345L] -> src.browser, src.jp_address, src.utils
rust_src/ (PyO3 module: land_value_core)
  lib.rs [42L] registers {PriceResult, LandPriceTokyo, TokyoGeocoder, normalize_addr, split_tokyo_municipality, parse_town_chome_block, num_to_kanji, build_oaza_chome_name, kanji_to_int}
  types.rs [35L] struct PriceResult
  coord.rs [85L] (lonlat_to_plane, ellipsoid_distance, ellipsoid_distances)
  landprice_tokyo.rs [586L] -> coord, types
  geocode_tokyo.rs [341L] -> jp_address
  jp_address.rs [360L] (normalize_addr, split_tokyo_municipality, parse_town_chome_block + PyO3 wrappers)
scripts/
  parallel_research.py [1072L] -> scripts._codex_precheck, scripts.codex_lockdown
  merge_address_patches.py [241L] (merge_patches_safe; マージ時に影響企業のoutput CSVを削除)
  merge_landprice.py [98L] standalone GeoJSON merge
  populate_company_master.py [228L] -> src.browser, src.company_config, src.stealth, src.utils
  populate_company_names.py [110L] -> src.company_config
  codex_lockdown.py [256L] standalone permission lockdown
  validate_ocr_accuracy.py [185L] -> src.pdf_extract
  loop_runner.py [91L] standalone subprocess launcher
  _codex_precheck.py [184L] standalone CSV/JSON checker
  _codex_geocode_check.py [34L] -> src.geocode_tokyo
config/
  magic_numbers.toml (SSOT: proxy/scrape/browser マジックナンバー)
  address_overrides.yaml
  price_overrides.yaml
  address_patches/*.precheck.json
  input.csv, input_full.csv
data/
  landprice/merged/ (GeoJSON)
  geocoding/geocode_ref_gaiku_tokyo_2024/ (CSV)
  cache/ {company_master.yaml, price_result_cache.json, geocode_result_cache.json, addr_overrides_hash.json, price_overrides_hash.json}
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
class BrowserService @src/browser.py:83 <-run.py, src/web_address_research.py, src/web_cache.py, src/company_metadata_fallback.py, src/rank_market_cap_ratio.py
class ProxyPool @src/stealth.py:35 <-run.py, scripts/populate_company_master.py
class WebAddressResearcher @src/web_address_research.py:39 <-run.py
class CompanyMetadata @src/company_metadata_fallback.py:23 <-run.py, src/rank_market_cap_ratio.py
class OutputRow @src/schema.py:51 <-src/anomaly.py, run.py
fn extract_major_facilities_land @src/pdf_extract.py:387 <-run.py, scripts/validate_ocr_accuracy.py
fn batch_extract_facilities @src/pdf_extract.py:485 <-run.py
fn calc_uncertainty_metrics @src/anomaly.py:23 <-run.py
fn detect_anomaly_warnings @src/anomaly.py:44 <-run.py
fn detect_duplicate_address_large_area @src/anomaly.py:103 <-run.py
fn should_accept_web_address @src/anomaly.py:74 <-run.py
fn load_company_master @src/company_config.py:29 <-run.py, src/rank_market_cap_ratio.py, scripts/populate_company_master.py, scripts/populate_company_names.py
fn save_company_master @src/company_config.py:236 <-run.py, src/rank_market_cap_ratio.py, scripts/populate_company_names.py
fn load_address_overrides @src/company_config.py:40 <-run.py
fn load_price_overrides @src/company_config.py:216 <-run.py
fn expand_site_splits @src/company_config.py:105 <-run.py
fn random_delay @src/stealth.py:22 <-src/stealth.py
fn fetch_from_irbank @src/company_metadata_fallback.py:71 <-run.py, src/rank_market_cap_ratio.py
fn file_md5 @src/cache.py:15 <-run.py
fn combined_md5 @src/cache.py:24 <-run.py
fn string_md5 @src/cache.py:32 <-run.py, src/web_address_research.py
fn load_json_dict @src/cache.py:52 <-run.py
fn save_json_dict @src/cache.py:65 <-run.py
fn load_sites_cache @src/cache.py:69 <-run.py
fn save_sites_cache @src/cache.py:100 <-run.py
fn is_transient_network_error @src/network.py:14 <-run.py
fn urlopen_with_retry @src/network.py:28
fn validate_url_not_private @src/utils.py:10 <-src/company_metadata_fallback.py, src/web_address_research.py, src/web_cache.py
fn normalize_addr @rust_src/jp_address.rs:127 <-src/jp_address.py(re-export), src/web_address_research.py
fn split_tokyo_municipality @rust_src/jp_address.rs:144 <-src/jp_address.py(re-export), src/web_address_research.py
fn merge_patches_safe @scripts/merge_address_patches.py:57 <-run.py
fn _infer_landuse_family @run.py:772 <-run.py (equipment_type→用途ファミリー推定, _EQUIPMENT_FAMILY_MAP参照)
fn generate_ranking @src/rank_market_cap_ratio.py:543 <-run.py
fn download_file @src/web_cache.py:25 <-run.py
fn is_pdf_file @src/web_cache.py:16 <-run.py
const OUTPUT_COLUMNS @src/schema.py:17 <-run.py
const RANKING_COLUMNS @src/schema.py:56 <-src/rank_market_cap_ratio.py
const MAGIC @src/config.py:60 <-src/stealth.py

# GRAPH

run.py -> {src.rank_market_cap_ratio, scripts.merge_address_patches, src.anomaly, src.browser, src.cache, src.company_config, src.company_metadata_fallback, src.geocode_tokyo, src.landprice_tokyo, src.network, src.pdf_extract, src.schema, src.stealth, src.utils, src.web_address_research, src.web_cache}
src.rank_market_cap_ratio -> {src.company_config, src.company_metadata_fallback, src.schema, src.browser}
src.anomaly -> {src.landprice_tokyo, src.schema}
src.browser -> {src.config} (subprocess: browser_service/server.js via pty)
src.cache -> {src.pdf_extract}
src.company_config -> {src.pdf_extract}
src.company_metadata_fallback -> {src.browser, src.utils}
src.stealth -> {src.config}
src.network -> {} (standalone)
src.web_address_research -> {src.browser, src.cache, src.jp_address, src.utils}
src.web_cache -> {src.browser, src.utils}
src.jp_address -> land_value_core (Rust)
src.landprice_tokyo -> land_value_core (Rust)
src.geocode_tokyo -> land_value_core (Rust)
land_value_core: landprice_tokyo -> {coord, types}; geocode_tokyo -> {jp_address}; jp_address (PyO3 direct)
scripts.parallel_research -> {scripts._codex_precheck, scripts.codex_lockdown}
scripts.populate_company_master -> {src.browser, src.company_config, src.stealth, src.utils}
scripts.populate_company_names -> {src.company_config}
scripts.validate_ocr_accuracy -> {src.pdf_extract}
scripts._codex_geocode_check -> {src.geocode_tokyo}

# CACHE

price_result_cache.json invalidated by MD5(data/landprice/merged/*.geojson + rust_src/landprice_tokyo.rs)
geocode_result_cache.json invalidated by MD5(data/geocoding/**/*.csv + rust_src/geocode_tokyo.rs)
facilities_land/{code}_sites.json invalidated by PDF stat(size+mtime) + cache_version (v5: equipment_type追加)
addr_overrides_hash.json invalidated by MD5(address_overrides.yaml per-company); triggers delete output/{code}_output.csv
price_overrides_hash.json invalidated by MD5(price_overrides.yaml per-company); triggers delete output/{code}_output.csv
market_cap_cache.json: external API, daily refresh (no auto-invalidation)
company_master.yaml: IRBank fallback cache, auto-populated on pipeline run (no auto-invalidation)
web_address/: external web results, volatile (no auto-invalidation)
