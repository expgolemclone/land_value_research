import argparse
import atexit
import csv
import gc
import logging
import math
import os
import re
import sys
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from src.cache import JsonDict
from src.company_config import CompanyMaster

import shtab

from scripts.merge_address_patches import merge_patches_safe
from src.anomaly import (
    CRITICAL_EVAL_MULTIPLE,
    calc_uncertainty_metrics,
    detect_anomaly_warnings,
    detect_duplicate_address_large_area,
    should_accept_web_address,
)
from src.browser import BrowserService
from src.cache import combined_md5, load_json_dict, load_sites_cache, save_json_dict, save_sites_cache, string_md5
from src.company_config import (
    SiteSplitEntry,
    expand_site_splits,
    load_address_overrides,
    load_company_master,
    load_price_overrides,
    save_company_master,
)
from src.company_metadata_fallback import fetch_from_irbank
from src.config import (
    ADDRESS_OVERRIDES_PATH,
    CACHE_DIR,
    COMPANY_MASTER_PATH,
    DEFAULT_OUTPUT_DIR,
    FACILITIES_CACHE_DIR,
    GAIKU_CSV,
    GEOCODE_CACHE_PATH,
    GEOCODE_RS,
    GEOJSON_PATH,
    INPUT_CSV,
    LANDPRICE_RS,
    MARKET_CAP_CACHE_PATH,
    OAZA_CSV,
    PATCH_DIR,
    PDF_CACHE_DIR,
    PRICE_CACHE_PATH,
    PRICE_OVERRIDES_PATH,
    PROJECT_ROOT,
    RUN_LOGS_DIR,
    WEB_ADDRESS_CACHE_DIR,
)
from src.geocode_tokyo import TokyoGeocoder
from src.landprice_tokyo import LandPriceTokyo, PriceResult
from src.network import is_transient_network_error
from src.pdf_extract import (
    FacilityLand,
    batch_extract_facilities,
    extract_facilities_section_text,
    extract_major_facilities_land,
)
from src.rank_market_cap_ratio import generate_ranking
from src.schema import (
    COL_ADDRESS,
    COL_ADDRESS_SOURCE,
    COL_ADDRESS_SOURCE_URL,
    COL_ANOMALY_WARNING,
    COL_BOOK_VALUE,
    COL_CODE,
    COL_COMPANY_NAME,
    COL_CONFIDENCE,
    COL_CONFIDENCE_SCORE,
    COL_ESTIMATED_VALUE,
    COL_GEOCODE_FACTOR,
    COL_GEOCODE_LEVEL,
    COL_KNN_DIST,
    COL_KNN_DIST_VAR,
    COL_KNN_IDS,
    COL_KNN_LANDUSE,
    COL_KNN_MAX_DIST,
    COL_KNN_PRICES,
    COL_LAND_AREA,
    COL_MARKET_CAP,
    COL_MULT,
    COL_MULT_RAW,
    COL_NEAREST_DIST,
    COL_NEAREST_ID,
    COL_NEAREST_LANDUSE,
    COL_PRICE_FACTOR,
    COL_PRICE_METHOD,
    COL_RATIO,
    COL_RATIO_RAW,
    COL_SITE_NAME,
    COL_TARGET_LANDUSE,
    COL_UNIT_PRICE,
    COL_UNREALIZED_GAIN,
    OUTPUT_COLUMNS,
    OutputRow,
)
from src.stealth import ProxyPool
from src.utils import ensure_dir
from src.web_address_research import WebAddressResearcher
from src.web_cache import download_file, is_pdf_file

logger = logging.getLogger(__name__)

CACHE_SAVE_INTERVAL = 10
COMPANY_RETRY_COUNT = 3
EXIT_CODE_MEMORY_LIMIT = 75
COMPANY_RETRY_BASE_DELAY_SEC = 2.0

_print_lock = threading.Lock()


def _tprint(*args: object, **kwargs: object) -> None:
    """Thread-safe print wrapper."""
    with _print_lock:
        print(*args, **kwargs)


OUTPUT_FIELDNAMES = list(OUTPUT_COLUMNS)


@dataclass
class RunContext:
    args: argparse.Namespace
    base_dir: str
    cache_dir: str
    facilities_cache_dir: str
    output_dir: str
    processed_lookup_dir: str
    price_cache_path: str
    geocode_cache_path: str
    company_master_path: str
    company_master: CompanyMaster
    addr_overrides: dict[str, dict[str, str | list[SiteSplitEntry]]]
    price_overrides: dict[str, dict[str, int]]
    market_cap_cache_path: str
    market_cap_cache: JsonDict
    geocoder: TokyoGeocoder
    web_addr: WebAddressResearcher
    landprice: LandPriceTokyo
    pool: ProxyPool
    browser: BrowserService
    price_cache_disk: JsonDict
    geocode_cache_disk: JsonDict
    cache_lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class CompanyResult:
    code: str
    company_name: str
    out_rows: list[OutputRow]
    sum_est: int
    tokyo_site_count: int


@dataclass
class _CompanyMeta:
    code: str
    company_name: str
    tokyo_sites: list[FacilityLand]
    all_sites_count: int
    mcap: float
    address_source_urls: list[str]


@dataclass
class _SiteResult:
    out_row: OutputRow
    est: int
    book: int
    est_raw: float
    book_raw: float


class CompanySkipError(Exception):
    """企業単位の処理をスキップすべきエラー."""


class TransientNetworkError(Exception):
    """一時的な通信エラー。一定回数の再試行対象。"""



def sanitize_filename_component(name: str) -> str:
    # Windowsで使えない文字を置換して, 出力ファイル名として安全化する
    safe = re.sub(r'[\\/:*?"<>|]', "_", name.strip())
    safe = re.sub(r"\s+", "_", safe)
    return safe or "unknown_company"


def resolve_path(base_dir: str, path_value: str) -> str:
    if os.path.isabs(path_value):
        return path_value
    return os.path.join(base_dir, path_value)


def load_csv_rows(input_path: str) -> list[list[str]]:
    encodings = ["utf-8-sig", "cp932"]
    last_error: Exception | None = None
    for enc in encodings:
        try:
            with open(input_path, encoding=enc, newline="") as f:
                return [row for row in csv.reader(f) if any((c or "").strip() for c in row)]
        except UnicodeDecodeError as e:
            last_error = e
    if last_error is not None:
        raise last_error
    return []  # pragma: no cover – encodings list is never empty


def parse_market_cap(raw: str) -> int | None:
    v = (raw or "").strip().replace(",", "")
    if not v:
        return None
    return round(float(v))


def parse_address_urls(raw: str) -> list[str]:
    return [x.strip() for x in (raw or "").split("|") if x.strip()]


def load_targets(input_path: str) -> list[dict[str, str]]:
    rows = load_csv_rows(input_path)
    if not rows:
        return []

    header_map = {h.strip().lower(): i for i, h in enumerate(rows[0])}
    has_header = any(k in header_map for k in ["code", "証券コード", "コード"])
    targets: list[dict[str, str]] = []

    if has_header:
        if "code" in header_map:
            code_key = "code"
        elif "証券コード" in header_map:
            code_key = "証券コード"
        else:
            code_key = "コード"
        for row in rows[1:]:
            code = row[header_map[code_key]].strip() if len(row) > header_map[code_key] else ""
            if not code:
                continue
            company_name = ""
            if "company_name" in header_map and len(row) > header_map["company_name"]:
                company_name = row[header_map["company_name"]].strip()
            elif "銘柄名" in header_map and len(row) > header_map["銘柄名"]:
                company_name = row[header_map["銘柄名"]].strip()
            targets.append(
                {
                    "code": code,
                    "company_name": company_name,
                    "pdf_url": row[header_map["securities_report_pdf_url"]].strip()
                    if "securities_report_pdf_url" in header_map and len(row) > header_map["securities_report_pdf_url"]
                    else "",
                    "market_cap": parse_market_cap(row[header_map["market_cap"]])
                    if "market_cap" in header_map and len(row) > header_map["market_cap"]
                    else None,
                    "address_source_urls": parse_address_urls(row[header_map["address_source_urls"]])
                    if "address_source_urls" in header_map and len(row) > header_map["address_source_urls"]
                    else [],
                }
            )
        return targets

    for row in rows:
        code = row[0].strip()
        if code:
            company_name = row[1].strip() if len(row) > 1 else ""
            targets.append(
                {
                    "code": code,
                    "company_name": company_name,
                    "pdf_url": "",
                    "market_cap": None,
                    "address_source_urls": [],
                }
            )
    return targets


def resolve_default_input(base_dir: str) -> str:
    return str(INPUT_CSV)


def migrate_legacy_pdf_cache(cache_dir: str) -> None:
    pdf_dir = os.path.join(cache_dir, "pdf")
    ensure_dir(pdf_dir)
    for name in os.listdir(cache_dir):
        if not name.endswith("_securities_report.pdf"):
            continue
        legacy_path = os.path.join(cache_dir, name)
        if not os.path.isfile(legacy_path):
            continue
        new_path = os.path.join(pdf_dir, name)
        if not os.path.exists(new_path):
            os.replace(legacy_path, new_path)


def get_pdf_path(cache_dir: str, code: str) -> str:
    pdf_dir = os.path.join(cache_dir, "pdf")
    ensure_dir(pdf_dir)
    new_pdf_path = os.path.join(pdf_dir, f"{code}_securities_report.pdf")
    legacy_pdf_path = os.path.join(cache_dir, f"{code}_securities_report.pdf")
    if not os.path.exists(new_pdf_path) and os.path.exists(legacy_pdf_path):
        os.replace(legacy_pdf_path, new_pdf_path)
    return new_pdf_path


def get_geocode_adjustment_factor(level: str, args: argparse.Namespace) -> float:
    if level == "gaiku":
        return float(args.geocode_factor_gaiku)
    if level == "oaza_chome":
        return float(args.geocode_factor_oaza_chome)
    if level == "muni_centroid":
        return float(args.geocode_factor_muni_centroid)
    return 1.0


def _setup_logging() -> None:
    log_dir = str(RUN_LOGS_DIR)
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(log_dir, f"{timestamp}.log")

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(fmt)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    logging.info("ログファイル: %s", log_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="land-value-run", description="東京都の土地推定時価を算出する")
    shtab.add_argument_to(parser)
    parser.add_argument("--input", default="")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--price-method", choices=["idw", "nearest"], default="idw")
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--p", type=int, default=3)
    parser.add_argument("--eps", type=float, default=1.0)
    parser.add_argument(
        "--geocode-factor-gaiku",
        type=float,
        default=1.0,
        help="住所解決レベルgaikuに対する地価単価補正係数(default: 1.0)",
    )
    parser.add_argument(
        "--geocode-factor-oaza-chome",
        type=float,
        default=0.95,
        help="住所解決レベルoaza_chomeに対する地価単価補正係数(default: 0.95)",
    )
    parser.add_argument(
        "--geocode-factor-muni-centroid",
        type=float,
        default=0.85,
        help="住所解決レベルmuni_centroidに対する地価単価補正係数(default: 0.85)",
    )
    parser.add_argument(
        "--allow-download",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="PDF未存在時のダウンロード可否(default: on)",
    )
    parser.add_argument(
        "--allow-web-address",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Webの公開情報で住所補完を使うか(default: on)",
    )
    parser.add_argument(
        "--skip-processed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="data/output に既存の *_output.csv がある企業をスキップするか(default: on)",
    )
    parser.add_argument(
        "--allow-auto-metadata",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="会社名/PDF URL/時価総額が不足時にIRBANKから自動補完するか(default: on)",
    )
    parser.add_argument(
        "--landuse-match",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="対象地点の最近傍公示点と同じ用途区分のみで地価推定するか(default: on)",
    )
    parser.add_argument(
        "--landuse-fallback-dist",
        type=float,
        default=1500.0,
        help="用途ファミリーツリーの最近傍がこの距離(m)を超えたら全用途ツリーにフォールバック(default: 1500.0)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="企業レベル並列処理のワーカー数(default: 4, 1で逐次処理)",
    )
    parser.add_argument(
        "--memory-limit",
        type=float,
        default=90,
        help="メモリ使用率(%%%%)がこの値を超えたらキャッシュを保存して終了する(default: 90, 0で無効化)",
    )
    parser.add_argument(
        "--max-restarts",
        type=int,
        default=10,
        help="メモリ制限終了時の最大再起動回数(default: 10, 0で無制限)",
    )
    parser.add_argument(
        "--no-auto-restart",
        action="store_true",
        default=False,
        help="メモリ制限終了時の自動再起動を無効化する",
    )
    parser.add_argument(
        "--proxy",
        default=None,
        help="Proxy URL (http://host:port, socks5://host:port). デフォルトは direct connection",
    )
    parser.add_argument(
        "--proxy-file",
        default=None,
        help="host:port:user:pass 形式のプロキシリストファイル",
    )
    return parser.parse_args()


def setup_environment(args: argparse.Namespace) -> RunContext:
    base_dir = str(PROJECT_ROOT)
    cache_dir = str(CACHE_DIR)
    facilities_cache_dir = str(FACILITIES_CACHE_DIR)
    price_cache_path = str(PRICE_CACHE_PATH)
    geocode_cache_path = str(GEOCODE_CACHE_PATH)
    company_master_path = str(COMPANY_MASTER_PATH)
    market_cap_cache_path = str(MARKET_CAP_CACHE_PATH)

    ensure_dir(cache_dir)
    ensure_dir(str(PDF_CACHE_DIR))
    migrate_legacy_pdf_cache(cache_dir)
    ensure_dir(facilities_cache_dir)

    company_master = load_company_master(company_master_path)
    addr_overrides = load_address_overrides(str(ADDRESS_OVERRIDES_PATH))
    price_overrides = load_price_overrides(str(PRICE_OVERRIDES_PATH))
    market_cap_cache = load_json_dict(market_cap_cache_path)

    geocoder = TokyoGeocoder(
        oaza_csv=str(OAZA_CSV),
        gaiku_csv=str(GAIKU_CSV),
    )
    if getattr(args, "proxy_file", None):
        pool: ProxyPool = ProxyPool.from_file(Path(args.proxy_file))
    elif getattr(args, "proxy", None):
        pool = ProxyPool.from_url(args.proxy)
    else:
        pool = ProxyPool.make_direct()

    browser = BrowserService()
    browser.start()

    web_addr = WebAddressResearcher(
        cache_dir=str(WEB_ADDRESS_CACHE_DIR),
        browser=browser,
        pool=pool,
    )
    geojson_path = str(GEOJSON_PATH)
    landprice = LandPriceTokyo(geojson_path=geojson_path)

    output_dir = resolve_path(base_dir, args.output)
    ensure_dir(output_dir)
    processed_lookup_dir = output_dir

    price_cache_disk = load_json_dict(price_cache_path)
    price_deps_hash = combined_md5(
        geojson_path,
        str(LANDPRICE_RS),
    )
    if price_cache_disk.get("_deps_hash") != price_deps_hash:
        logger.info("地価推定の依存変更を検出: price_result_cache をクリア")
        price_cache_disk = {"_deps_hash": price_deps_hash}

    geocode_cache_disk = load_json_dict(geocode_cache_path)
    geocode_deps_hash = combined_md5(
        str(GAIKU_CSV),
        str(GEOCODE_RS),
    )
    if geocode_cache_disk.get("_deps_hash") != geocode_deps_hash:
        logger.info("ジオコード依存変更を検出: geocode_result_cache をクリア")
        geocode_cache_disk = {"_deps_hash": geocode_deps_hash}

    ctx = RunContext(
        args=args,
        base_dir=base_dir,
        cache_dir=cache_dir,
        facilities_cache_dir=facilities_cache_dir,
        output_dir=output_dir,
        processed_lookup_dir=processed_lookup_dir,
        price_cache_path=price_cache_path,
        geocode_cache_path=geocode_cache_path,
        company_master_path=company_master_path,
        company_master=company_master,
        addr_overrides=addr_overrides,
        price_overrides=price_overrides,
        market_cap_cache_path=market_cap_cache_path,
        market_cap_cache=market_cap_cache,
        geocoder=geocoder,
        web_addr=web_addr,
        landprice=landprice,
        pool=pool,
        browser=browser,
        price_cache_disk=price_cache_disk,
        geocode_cache_disk=geocode_cache_disk,
    )
    atexit.register(save_caches, ctx)
    return ctx


def _invalidate_stale_override_csvs(ctx: RunContext) -> list[str]:
    """Delete output CSVs for companies whose addr/price overrides changed since last run."""
    import json

    invalidated: list[str] = []

    def _check_overrides(
        overrides_dict: dict[str, object],
        hash_filename: str,
        label: str,
    ) -> None:
        hash_path = os.path.join(ctx.cache_dir, hash_filename)
        old_hashes = load_json_dict(hash_path)
        new_hashes: dict[str, str] = {}

        for code, overrides in overrides_dict.items():
            serialized = json.dumps(overrides, sort_keys=True, ensure_ascii=False, default=str)
            h = string_md5(serialized)
            new_hashes[code] = h

            if old_hashes.get(code) != h:
                csv_path = os.path.join(
                    ctx.processed_lookup_dir,
                    f"{sanitize_filename_component(code)}_output.csv",
                )
                if os.path.exists(csv_path):
                    os.remove(csv_path)
                    invalidated.append(code)
                    logger.info("%s変更: %s のCSVを削除", label, code)

        for code in old_hashes:
            if code not in new_hashes:
                csv_path = os.path.join(
                    ctx.processed_lookup_dir,
                    f"{sanitize_filename_component(code)}_output.csv",
                )
                if os.path.exists(csv_path):
                    os.remove(csv_path)
                    invalidated.append(code)
                    logger.info("%s削除: %s のCSVを削除", label, code)

        save_json_dict(hash_path, new_hashes)

    _check_overrides(ctx.addr_overrides, "addr_overrides_hash.json", "住所オーバーライド")
    _check_overrides(ctx.price_overrides, "price_overrides_hash.json", "地価オーバーライド")
    return invalidated


def _filter_targets(
    targets: list[dict[str, str]],
    ctx: RunContext,
) -> tuple[list[dict[str, str]], list[tuple[str, str, str]]]:
    targets_to_process: list[dict[str, str]] = []
    skipped: list[tuple[str, str, str]] = []
    for t in targets:
        code = t["code"]
        meta = ctx.company_master.get(code, {})
        company_name = t["company_name"] or meta.get("company_name", code)
        output_filename = f"{sanitize_filename_component(code)}_output.csv"
        out_path = os.path.join(ctx.output_dir, output_filename)
        processed_out_path = os.path.join(ctx.processed_lookup_dir, output_filename)
        if ctx.args.skip_processed and os.path.exists(processed_out_path):
            skipped.append((code, company_name, processed_out_path))
            continue
        t2 = dict(t)
        t2["_resolved_company_name"] = company_name
        t2["_output_path"] = out_path
        targets_to_process.append(t2)
    return targets_to_process, skipped


def _resolve_company_metadata(
    t: dict[str, str],
    company_index: int,
    total_companies: int,
    ctx: RunContext,
) -> _CompanyMeta:
    code = t["code"]
    meta = ctx.company_master.get(code, {})
    company_name = t["_resolved_company_name"] or meta.get("company_name", "")
    _tprint(f"[{company_index}/{total_companies}] 開始: {code} {company_name}")
    pdf_url = t["pdf_url"] or meta.get("securities_report_pdf_url", "")
    address_source_urls = t["address_source_urls"] or list(meta.get("address_source_urls", []) or [])
    fallback = None
    if ctx.args.allow_auto_metadata and (not company_name or company_name == code or not pdf_url):
        fallback = fetch_from_irbank(code, browser=ctx.browser, pool=ctx.pool)
        if (not company_name or company_name == code) and fallback.company_name:
            company_name = fallback.company_name
        if not pdf_url and fallback.securities_report_pdf_url:
            pdf_url = fallback.securities_report_pdf_url
        if fallback.address_source_url and fallback.address_source_url not in address_source_urls:
            address_source_urls.append(fallback.address_source_url)
        # IRBankから取得した情報をcompany_masterに追記（後続処理・永続化用）
        if fallback.company_name or fallback.securities_report_pdf_url:
            with ctx.cache_lock:
                existing = ctx.company_master.get(code, {})
                updated = dict(existing)
                if fallback.company_name and not existing.get("company_name"):
                    updated["company_name"] = fallback.company_name
                if fallback.securities_report_pdf_url and not existing.get("securities_report_pdf_url"):
                    updated["securities_report_pdf_url"] = fallback.securities_report_pdf_url
                if fallback.address_source_url:
                    existing_urls = list(existing.get("address_source_urls") or [])
                    if fallback.address_source_url not in existing_urls:
                        existing_urls.append(fallback.address_source_url)
                        updated["address_source_urls"] = existing_urls
                if updated != existing:
                    ctx.company_master[code] = updated
    if not company_name or not pdf_url:
        raise CompanySkipError(
            f"証券コード{code}の会社情報が不足しています."
            " config/input.csvに company_name,securities_report_pdf_url を追加するか,"
            " company_master.yamlへ登録してください."
        )
    if pdf_url and pdf_url not in address_source_urls:
        address_source_urls.append(pdf_url)
    pdf_path = get_pdf_path(ctx.cache_dir, code)
    if os.path.exists(pdf_path) and not is_pdf_file(pdf_path):
        os.remove(pdf_path)

    if not os.path.exists(pdf_path):
        if not ctx.args.allow_download:
            raise CompanySkipError(
                f"PDFが見つかりません: {pdf_path} ネットワーク無し環境では, 事前にdata/cache/pdfへ配置してください."
            )
        try:
            download_file(pdf_url, pdf_path, browser=ctx.browser, pool=ctx.pool)
        except (ValueError, urllib.error.URLError, OSError) as e:
            if is_transient_network_error(e):
                raise TransientNetworkError(f"証券コード{code}の有報PDF取得で一時通信エラー: {e}") from e
            raise CompanySkipError(f"証券コード{code}の有報PDF取得に失敗しました: {e}") from e

    # PDFをWeb住所調査キャッシュにも登録（二重ダウンロード防止）
    if os.path.exists(pdf_path) and pdf_url:
        ctx.web_addr.seed_cache(pdf_url, pdf_path)

    sites_cache_path = os.path.join(ctx.facilities_cache_dir, f"{code}_sites.json")
    sites = load_sites_cache(sites_cache_path, pdf_path)
    if sites is None:
        sites = extract_major_facilities_land(pdf_path)
        save_sites_cache(sites_cache_path, pdf_path, sites)

    # 設備の状況テキストキャッシュ
    text_cache_path = os.path.join(ctx.facilities_cache_dir, f"{code}_facilities_text.txt")
    if not os.path.exists(text_cache_path):
        facilities_text = extract_facilities_section_text(pdf_path)
        if facilities_text:
            with open(text_cache_path, "w", encoding="utf-8") as f:
                f.write(facilities_text)

    # サイト分割展開（tokyoフィルタ前に実施: 分割先が他県になるケースに対応）
    company_overrides = ctx.addr_overrides.get(code, {})
    if any(isinstance(v, list) for v in company_overrides.values()):
        sites, flat_overrides = expand_site_splits(sites, company_overrides)
        with ctx.cache_lock:
            ctx.addr_overrides[code] = flat_overrides
    tokyo_sites = [s for s in sites if s.location_short.startswith("東京都")]
    _tprint(f"[{company_index}/{total_companies}] 拠点: 全{len(sites)}件, 東京都対象{len(tokyo_sites)}件")

    mcap = t["market_cap"]
    if mcap is None:
        today = date.today().isoformat()
        with ctx.cache_lock:
            cached = ctx.market_cap_cache.get(code)
        if cached and cached.get("fetched_date") == today:
            mcap = cached["market_cap_yen"]
        elif ctx.args.allow_auto_metadata:
            if fallback is None:
                fallback = fetch_from_irbank(code, browser=ctx.browser, pool=ctx.pool)
            if fallback.market_cap_yen is not None:
                mcap = fallback.market_cap_yen
                with ctx.cache_lock:
                    ctx.market_cap_cache[code] = {"market_cap_yen": mcap, "fetched_date": today}
    if mcap is None:
        raise CompanySkipError(
            f"証券コード{code}の時価総額が不足しています. config/input.csvに market_cap を追加してください."
        )
    return _CompanyMeta(
        code=code,
        company_name=company_name,
        tokyo_sites=tokyo_sites,
        all_sites_count=len(sites),
        mcap=float(mcap),
        address_source_urls=address_source_urls,
    )


def _geocode_address(full_addr: str, ctx: RunContext) -> tuple[float, float, str]:
    """Geocode an address using disk cache or geocoder.

    Uses double-checked locking so that the heavy geocoder.geocode() call
    runs outside the lock, allowing other threads to proceed concurrently.
    """
    with ctx.cache_lock:
        dg = ctx.geocode_cache_disk.get(full_addr)
        if isinstance(dg, list) and len(dg) == 3:
            return (float(dg[0]), float(dg[1]), str(dg[2]))

    # Compute outside lock — geocoder is thread-safe (Rust &self, no interior mutation)
    geo = ctx.geocoder.geocode(full_addr)

    with ctx.cache_lock:
        existing = ctx.geocode_cache_disk.get(full_addr)
        if isinstance(existing, list) and len(existing) == 3:
            return (float(existing[0]), float(existing[1]), str(existing[2]))
        ctx.geocode_cache_disk[full_addr] = [float(geo[0]), float(geo[1]), str(geo[2])]
    return geo


def _deserialize_price_result(dp: dict[str, object]) -> PriceResult:
    return PriceResult(
        unit_price=int(dp["unit_price"]),
        nearest_id=str(dp["nearest_id"]),
        nearest_dist_m=float(dp["nearest_dist_m"]),
        knn_ids=[str(x) for x in dp.get("knn_ids", [])],
        knn_dist_m=[float(x) for x in dp.get("knn_dist_m", [])],
        knn_prices=[int(x) for x in dp.get("knn_prices", [])],
    )


# 設備内容 → 用途ファミリー
_EQUIPMENT_FAMILY_MAP: dict[str, str] = {
    # 工業系
    "タンク": "工業系", "工場": "工業系", "倉庫": "工業系", "製造": "工業系",
    "洗濯": "工業系", "車庫": "工業系", "整備": "工業系", "物流": "工業系",
    "配送": "工業系", "リサイクル": "工業系", "プラント": "工業系",
    "生産": "工業系", "作業所": "工業系", "油槽": "工業系",
    # 商業系
    "事務所": "商業系", "本社機能": "商業系", "店舗": "商業系", "営業所": "商業系",
    "賃貸ビル": "商業系", "賃貸オフィス": "商業系",
    "競馬場": "商業系", "斎場": "商業系", "ホテル": "商業系", "婚礼": "商業系",
    "販売": "商業系", "賃貸": "商業系", "商業": "商業系", "展示": "商業系",
    # 住居系
    "社宅": "住居系", "寮": "住居系", "社員寮": "住居系", "独身寮": "住居系",
    "賃貸マンション": "住居系",
}


def _infer_landuse_family(equipment_type: str) -> str | None:
    """設備内容から用途ファミリーを推定。推定不可なら None。"""
    for keyword, family in _EQUIPMENT_FAMILY_MAP.items():
        if keyword in equipment_type:
            return family
    return None


def _estimate_price(lat: float, lon: float, target_landuse_kind: str, ctx: RunContext) -> PriceResult:
    """Estimate land price using disk cache or landprice engine.

    Uses double-checked locking so that the heavy landprice computation
    runs outside the lock, allowing other threads to proceed concurrently.
    """
    disk_key = (
        f"{lat:.15f}|{lon:.15f}|{ctx.args.price_method}|{int(ctx.args.k)}|{int(ctx.args.p)}|"
        f"{float(ctx.args.eps):.15f}|{target_landuse_kind}"
    )
    with ctx.cache_lock:
        dp = ctx.price_cache_disk.get(disk_key)
        if isinstance(dp, dict) and "unit_price" in dp:
            return _deserialize_price_result(dp)

    # Compute outside lock — landprice engine is thread-safe (Rust &self, no interior mutation)
    if ctx.args.price_method == "nearest":
        pr = ctx.landprice.nearest(
            lat=lat,
            lon=lon,
            landuse_kind=(target_landuse_kind or None),
        )
    else:
        pr = ctx.landprice.idw(
            lat=lat,
            lon=lon,
            k=ctx.args.k,
            p=ctx.args.p,
            eps=ctx.args.eps,
            landuse_kind=(target_landuse_kind or None),
        )

    with ctx.cache_lock:
        dp = ctx.price_cache_disk.get(disk_key)
        if isinstance(dp, dict) and "unit_price" in dp:
            return _deserialize_price_result(dp)
        ctx.price_cache_disk[disk_key] = {
            "unit_price": int(pr.unit_price),
            "nearest_id": str(pr.nearest_id),
            "nearest_dist_m": float(pr.nearest_dist_m),
            "knn_ids": [str(x) for x in pr.knn_ids],
            "knn_dist_m": [float(x) for x in pr.knn_dist_m],
            "knn_prices": [int(x) for x in pr.knn_prices],
            "landuse_kind": target_landuse_kind,
        }
    return pr


def _process_site(
    code: str,
    company_name: str,
    s: FacilityLand,
    mcap: float,
    address_source_urls: list[str],
    ctx: RunContext,
) -> _SiteResult:
    full_addr = ctx.addr_overrides.get(code, {}).get(s.site_name)
    addr_source = "override"
    addr_source_url = ""
    if not full_addr:
        if ctx.args.allow_web_address and address_source_urls:
            cand = ctx.web_addr.resolve(
                site_name=s.site_name,
                location_short=s.location_short,
                source_urls=address_source_urls,
            )
            if cand and should_accept_web_address(s.site_name, cand.score, location_has_hoka=s.location_has_hoka):
                full_addr = cand.address
                addr_source = "web"
                addr_source_url = cand.source_url

    if not full_addr:
        full_addr = s.location_short
        addr_source = "securities_report"

    lat, lon, geocode_level = _geocode_address(full_addr, ctx)

    price_override = ctx.price_overrides.get(code, {}).get(s.site_name)
    if price_override is not None:
        unit_price = price_override
        unit_price_raw = float(price_override)
        total_factor = 1.0
        method = "override"
        pr = PriceResult(
            unit_price=price_override,
            nearest_id="",
            nearest_dist_m=0.0,
            knn_ids=[],
            knn_dist_m=[],
            knn_prices=[],
        )
        geocode_factor = 1.0
        dist_var, max_knn_dist_m, confidence_score, confidence_label = 0.0, 0.0, 1.0, "override"
        target_landuse_kind = ""
        nearest_landuse_kind = ""
        knn_landuse_kinds = []
    else:
        target_landuse_kind = ""
        if ctx.args.landuse_match:
            # 設備内容からファミリーを推定 → ファミリーツリーで最近傍検索
            family = _infer_landuse_family(s.equipment_type)
            if family:
                seed_pr = ctx.landprice.nearest(lat=lat, lon=lon, landuse_kind=family)
            else:
                seed_pr = ctx.landprice.nearest(lat=lat, lon=lon)
            # 距離フォールバック: 用途ツリーの最近傍が閾値を超えたらtree_allで再検索
            if family and seed_pr.nearest_dist_m > ctx.args.landuse_fallback_dist:
                seed_pr_all = ctx.landprice.nearest(lat=lat, lon=lon)
                target_landuse_kind = ctx.landprice.get_point_landuse_kind(seed_pr_all.nearest_id)
            else:
                target_landuse_kind = ctx.landprice.get_point_landuse_kind(seed_pr.nearest_id)

        pr = _estimate_price(lat, lon, target_landuse_kind, ctx)

        dist_var, max_knn_dist_m, confidence_score, confidence_label = calc_uncertainty_metrics(pr)
        geocode_factor = get_geocode_adjustment_factor(geocode_level, ctx.args)
        total_factor = geocode_factor
        unit_price_raw = float(pr.unit_price) * total_factor
        unit_price = int(round(unit_price_raw))
        method = "nearest" if ctx.args.price_method == "nearest" else f"idw(k={ctx.args.k},p={ctx.args.p})"
        if ctx.args.landuse_match:
            method = f"{method}+landuse_match"
        nearest_landuse_kind = ctx.landprice.get_point_landuse_kind(pr.nearest_id)
        knn_landuse_kinds = ctx.landprice.get_landuse_kinds_for_ids(pr.knn_ids)

    est_raw = unit_price_raw * float(s.land_area_m2)
    est = int(round(float(unit_price) * float(s.land_area_m2)))
    book_raw = float(s.land_book_value_yen)
    book = int(round(book_raw))
    profit = est - book
    mult_raw = (est_raw / book_raw) if not math.isclose(book_raw, 0.0) else None
    mcap_ratio_raw = est_raw / float(mcap) if mcap else None
    anomaly_warnings = detect_anomaly_warnings(
        land_area_m2=float(s.land_area_m2),
        geocode_level=geocode_level,
        confidence_label=confidence_label,
        max_knn_dist_m=max_knn_dist_m,
        location_has_hoka=s.location_has_hoka,
    )
    if mult_raw is not None and mult_raw >= CRITICAL_EVAL_MULTIPLE:
        anomaly_warnings.append("評価倍率閾値超過")
    anomaly_text = " | ".join(anomaly_warnings)
    if anomaly_warnings:
        _tprint(
            f"Warn(anomaly): {code} {s.site_name} {geocode_level} "
            f"area={float(s.land_area_m2):.2f} warnings={anomaly_text}"
        )
    out_row: dict[str, object] = {
        COL_CODE: code,
        COL_COMPANY_NAME: company_name,
        COL_SITE_NAME: s.site_name,
        COL_ADDRESS: full_addr,
        COL_ADDRESS_SOURCE: addr_source,
        COL_ADDRESS_SOURCE_URL: addr_source_url,
        COL_GEOCODE_LEVEL: geocode_level,
        COL_LAND_AREA: f"{s.land_area_m2:.2f}",
        COL_UNIT_PRICE: unit_price,
        COL_PRICE_FACTOR: f"{total_factor:.6f}",
        COL_GEOCODE_FACTOR: f"{geocode_factor:.6f}",
        COL_PRICE_METHOD: method,
        COL_TARGET_LANDUSE: target_landuse_kind,
        COL_NEAREST_LANDUSE: nearest_landuse_kind,
        COL_NEAREST_ID: pr.nearest_id,
        COL_NEAREST_DIST: f"{pr.nearest_dist_m:.3f}",
        COL_KNN_IDS: "|".join(pr.knn_ids),
        COL_KNN_LANDUSE: "|".join(knn_landuse_kinds),
        COL_KNN_DIST: "|".join([f"{d:.3f}" for d in pr.knn_dist_m]),
        COL_KNN_PRICES: "|".join([str(int(x)) for x in pr.knn_prices]),
        COL_KNN_DIST_VAR: f"{dist_var:.3f}",
        COL_KNN_MAX_DIST: f"{max_knn_dist_m:.3f}",
        COL_CONFIDENCE_SCORE: f"{confidence_score:.6f}",
        COL_CONFIDENCE: confidence_label,
        COL_ANOMALY_WARNING: anomaly_text,
        COL_ESTIMATED_VALUE: est,
        COL_BOOK_VALUE: book,
        COL_UNREALIZED_GAIN: profit,
        COL_MULT_RAW: ("" if mult_raw is None else f"{mult_raw:.12f}"),
        COL_MULT: ("" if mult_raw is None else f"{mult_raw:.3f}"),
        COL_MARKET_CAP: int(mcap),
        COL_RATIO_RAW: ("" if mcap_ratio_raw is None else f"{mcap_ratio_raw:.12f}"),
        COL_RATIO: ("" if mcap_ratio_raw is None else f"{mcap_ratio_raw:.3f}"),
    }
    return _SiteResult(
        out_row=out_row,
        est=est,
        book=book,
        est_raw=est_raw,
        book_raw=book_raw,
    )


def _postprocess_duplicate_anomalies(
    code: str,
    out_rows: list[OutputRow],
) -> None:
    """Detect duplicate-address anomalies and append warning labels to rows."""
    duplicate_warnings = detect_duplicate_address_large_area(out_rows)

    for hit in duplicate_warnings:
        _tprint(f"Warn(anomaly): {code} duplicate_address {hit.detail}")
        for row in hit.rows:
            warning_label = "同一住所かつ大面積の複数拠点"
            old = str(row.get(COL_ANOMALY_WARNING, "") or "").strip()
            row[COL_ANOMALY_WARNING] = f"{old} | {warning_label}" if old else warning_label


def process_company(
    t: dict[str, str],
    company_index: int,
    total_companies: int,
    ctx: RunContext,
) -> CompanyResult:
    cm = _resolve_company_metadata(t, company_index, total_companies, ctx)
    code, company_name, tokyo_sites, mcap = cm.code, cm.company_name, cm.tokyo_sites, cm.mcap

    sum_est = 0
    sum_book = 0
    sum_est_raw = 0.0
    sum_book_raw = 0.0
    out_rows: list[OutputRow] = []

    total_tokyo_sites = len(tokyo_sites)
    for site_index, s in enumerate(tokyo_sites, start=1):
        _tprint(f"[{company_index}/{total_companies}][{site_index}/{total_tokyo_sites}] 解析中: {code} {s.site_name}")
        try:
            sr = _process_site(code, company_name, s, mcap, cm.address_source_urls, ctx)
        except Exception as e:
            logger.warning("サイト処理スキップ: %s %s %s: %s", code, s.site_name, type(e).__name__, e)
            continue
        out_rows.append(sr.out_row)
        sum_est += sr.est
        sum_book += sr.book
        sum_est_raw += sr.est_raw
        sum_book_raw += sr.book_raw

    _postprocess_duplicate_anomalies(code, out_rows)

    # 東京都合計行(東京都の対象が0件でも必ず出力する)
    profit = sum_est - sum_book
    mult_raw = (sum_est_raw / sum_book_raw) if not math.isclose(sum_book_raw, 0.0) else None
    mcap_ratio_raw = (sum_est_raw / float(mcap)) if mcap else None
    total_row = dict.fromkeys(OUTPUT_FIELDNAMES, "")
    total_row.update(
        {
            COL_CODE: code,
            COL_COMPANY_NAME: company_name,
            COL_SITE_NAME: "東京都合計",
            COL_PRICE_METHOD: (
                (f"idw(k={ctx.args.k},p={ctx.args.p})" if ctx.args.price_method == "idw" else "nearest")
                + ("+landuse_match" if ctx.args.landuse_match else "")
            ),
            COL_ESTIMATED_VALUE: sum_est,
            COL_BOOK_VALUE: sum_book,
            COL_UNREALIZED_GAIN: profit,
            COL_MULT_RAW: ("" if mult_raw is None else f"{mult_raw:.12f}"),
            COL_MULT: ("" if mult_raw is None else f"{mult_raw:.3f}"),
            COL_MARKET_CAP: int(mcap),
            COL_RATIO_RAW: ("" if mcap_ratio_raw is None else f"{mcap_ratio_raw:.12f}"),
            COL_RATIO: ("" if mcap_ratio_raw is None else f"{mcap_ratio_raw:.3f}"),
        }
    )
    out_rows.append(total_row)
    _tprint(
        f"[{company_index}/{total_companies}] 完了: {code} 東京都拠点{len(tokyo_sites)}件, 推定時価合計{sum_est:,}円"
    )

    return CompanyResult(
        code=code,
        company_name=company_name,
        out_rows=out_rows,
        sum_est=sum_est,
        tokyo_site_count=len(tokyo_sites),
    )


def _write_single_result(result: CompanyResult, out_path: str) -> None:
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_FIELDNAMES)
        w.writeheader()
        for r in result.out_rows:
            w.writerow(r)


def _get_memory_usage_percent() -> float:
    """Return system memory usage as a percentage (0-100)."""
    if sys.platform == "win32":
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX(dwLength=ctypes.sizeof(MEMORYSTATUSEX))
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return float(stat.dwMemoryLoad)
    else:
        try:
            with open("/proc/meminfo") as f:
                info: dict[str, int] = {}
                for line in f:
                    parts = line.split()
                    if parts[0] in ("MemTotal:", "MemAvailable:"):
                        info[parts[0]] = int(parts[1])
                    if len(info) == 2:
                        break
            total = info["MemTotal:"]
            available = info["MemAvailable:"]
            return (total - available) / total * 100
        except (KeyError, OSError, IndexError, ValueError) as e:
            logger.debug("メモリ情報の取得に失敗: %s", e)
            return 0.0


def _memory_watchdog(ctx: RunContext, limit_percent: float, check_interval: float = 5.0) -> None:
    """Daemon thread: check memory usage periodically, terminate if over limit."""
    while True:
        time.sleep(check_interval)
        usage = _get_memory_usage_percent()
        if usage >= limit_percent:
            logger.critical("メモリ使用率 %.1f%% (閾値 %.0f%%) — キャッシュ保存して終了します", usage, limit_percent)
            try:
                save_caches(ctx)
            except Exception:
                logger.exception("キャッシュ保存に失敗しました")
            os._exit(EXIT_CODE_MEMORY_LIMIT)


def save_caches(ctx: RunContext) -> None:
    with ctx.cache_lock:
        save_json_dict(ctx.price_cache_path, ctx.price_cache_disk)
        save_json_dict(ctx.geocode_cache_path, ctx.geocode_cache_disk)
        save_json_dict(ctx.market_cap_cache_path, ctx.market_cap_cache)
        save_company_master(ctx.company_master_path, ctx.company_master)
    ctx.web_addr.flush()


def _pre_download_pdf(t: dict[str, str], ctx: RunContext) -> None:
    """Phase 1: PDF URLが既知のターゲットのPDFを事前ダウンロード."""
    code = t["code"]
    pdf_path = get_pdf_path(ctx.cache_dir, code)
    if os.path.exists(pdf_path) and is_pdf_file(pdf_path):
        return
    if os.path.exists(pdf_path):
        os.remove(pdf_path)
    meta = ctx.company_master.get(code, {})
    pdf_url = t["pdf_url"] or meta.get("securities_report_pdf_url", "")
    if not pdf_url or not ctx.args.allow_download:
        return
    try:
        download_file(pdf_url, pdf_path, browser=ctx.browser, pool=ctx.pool)
    except Exception as e:
        logger.warning("PDF事前ダウンロード失敗(後で再試行): %s: %s", code, e)


def _pre_download_pdfs(
    targets: list[dict[str, str]],
    max_workers: int,
    ctx: RunContext,
) -> None:
    """ThreadPoolExecutorでPDFを事前ダウンロード (I/O bound)."""
    need_download = []
    for t in targets:
        p = get_pdf_path(ctx.cache_dir, t["code"])
        if not os.path.exists(p) or not is_pdf_file(p):
            need_download.append(t)
    if not need_download:
        return
    dl_workers = max(1, min(max_workers, len(need_download)))
    logger.info("PDF事前ダウンロード開始: %d件 (workers=%d)", len(need_download), dl_workers)
    with ThreadPoolExecutor(max_workers=dl_workers) as executor:
        futures = {executor.submit(_pre_download_pdf, t, ctx): t for t in need_download}
        failed = 0
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                failed += 1
        if failed:
            logger.warning("PDF事前ダウンロード完了: %d/%d件失敗", failed, len(need_download))
        else:
            logger.info("PDF事前ダウンロード完了: %d件", len(need_download))


def _process_company_with_retry(
    t: dict[str, str],
    company_index: int,
    total_companies: int,
    ctx: RunContext,
) -> tuple[CompanyResult | None, str]:
    """Process a company with retry logic. Returns (result, error_message)."""
    code = t["code"]
    company_name = t.get("_resolved_company_name", code)
    for attempt in range(1, COMPANY_RETRY_COUNT + 1):
        try:
            return process_company(t, company_index, total_companies, ctx), ""
        except TransientNetworkError as e:
            if attempt >= COMPANY_RETRY_COUNT:
                msg = f"{type(e).__name__}: {e}"
                logger.error("企業処理スキップ: %s %s %s", code, company_name, msg)
                return None, msg
            delay_sec = COMPANY_RETRY_BASE_DELAY_SEC * (2 ** (attempt - 1))
            logger.warning(
                "企業処理再試行: %s %s attempt=%d/%d wait=%.1fs reason=%s",
                code,
                company_name,
                attempt,
                COMPANY_RETRY_COUNT,
                delay_sec,
                e,
            )
            time.sleep(delay_sec)
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            logger.error("企業処理スキップ: %s %s %s", code, company_name, msg)
            return None, msg
    return None, "max retries exceeded"


_WORKER_ENV_VAR = "_LAND_VALUE_WORKER"
_RESTART_DELAY_SEC = 3


def _run_with_restart(args: argparse.Namespace) -> None:
    """Subprocess loop: re-launch run.py in worker mode on memory-limit exit."""
    import subprocess

    run_py = os.path.abspath(__file__)
    cmd = [sys.executable, run_py, *sys.argv[1:]]
    env = {**os.environ, _WORKER_ENV_VAR: "1"}

    restart_count = 0
    while True:
        print(f"--- run.py 起動 (restart #{restart_count}) ---")
        result = subprocess.run(cmd, env=env)

        if result.returncode == 0:
            print("--- run.py 正常終了 ---")
            break

        if result.returncode == EXIT_CODE_MEMORY_LIMIT:
            restart_count += 1
            if args.max_restarts > 0 and restart_count >= args.max_restarts:
                print(f"--- 最大再起動回数 ({args.max_restarts}) に達しました。終了します ---")
                sys.exit(EXIT_CODE_MEMORY_LIMIT)
            print(f"--- メモリ制限により終了。{_RESTART_DELAY_SEC}秒後に再起動します (#{restart_count}) ---")
            time.sleep(_RESTART_DELAY_SEC)
            continue

        print(f"--- run.py がエラー終了しました (exit code: {result.returncode})。再起動しません ---")
        sys.exit(result.returncode)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    args = parse_args()

    # Wrapper mode: if not in worker subprocess, launch restart loop
    if not args.no_auto_restart and os.environ.get(_WORKER_ENV_VAR) != "1":
        _run_with_restart(args)
        return

    _main_worker(args)


def _main_worker(args: argparse.Namespace) -> None:
    """Main processing pipeline (runs inside worker subprocess or with --no-auto-restart)."""
    _setup_logging()
    ctx = setup_environment(args)
    try:
        _run_pipeline(args, ctx)
    finally:
        ctx.browser.shutdown()


def _run_pipeline(args: argparse.Namespace, ctx: RunContext) -> None:
    if args.memory_limit > 0:
        watchdog = threading.Thread(target=_memory_watchdog, args=(ctx, args.memory_limit), daemon=True)
        watchdog.start()

    invalidated = _invalidate_stale_override_csvs(ctx)
    if invalidated:
        logger.info("住所オーバーライド変更によりCSV削除: %d社", len(invalidated))

    input_path = resolve_path(ctx.base_dir, args.input) if args.input else resolve_default_input(ctx.base_dir)
    targets = load_targets(input_path)
    if not targets:
        raise SystemExit(f"証券コードがありません: {input_path}")

    targets_to_process, skipped = _filter_targets(targets, ctx)

    for code, company_name, out_path in skipped:
        logger.info("Skip(調査済み): %s %s -> %s", code, company_name, out_path)

    if skipped:
        logger.info("調査済みスキップ件数: %d", len(skipped))

    if targets_to_process:
        total_companies = len(targets_to_process)
        max_workers = max(1, min(args.workers, total_companies))
        logger.info("処理開始: %d社 (workers=%d)", total_companies, max_workers)

        # --- Phase 1: PDF事前ダウンロード (I/O bound → ThreadPoolExecutor) ---
        _pre_download_pdfs(targets_to_process, max_workers, ctx)

        # --- Phase 2: バッチPDF並列抽出 (CPU bound → ProcessPoolExecutor) ---
        uncached_pdfs: dict[str, str] = {}
        for t in targets_to_process:
            code = t["code"]
            pdf_path = get_pdf_path(ctx.cache_dir, code)
            if not os.path.exists(pdf_path):
                continue
            sites_cache_path = os.path.join(ctx.facilities_cache_dir, f"{code}_sites.json")
            if load_sites_cache(sites_cache_path, pdf_path) is None:
                uncached_pdfs[code] = pdf_path

        if uncached_pdfs:
            pdf_workers = max(1, min(max_workers, len(uncached_pdfs), os.cpu_count() or 4))
            logger.info("PDF並列抽出開始: %d件 (workers=%d)", len(uncached_pdfs), pdf_workers)
            batch_results = batch_extract_facilities(uncached_pdfs, max_workers=pdf_workers)
            for code, sites in batch_results.items():
                sites_cache_path = os.path.join(ctx.facilities_cache_dir, f"{code}_sites.json")
                pdf_path = uncached_pdfs[code]
                save_sites_cache(sites_cache_path, pdf_path, sites)
            logger.info("PDF並列抽出完了: %d件", len(batch_results))

        failed_companies: list[tuple[str, str, str]] = []
        written_count = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_target = {}
            for company_index, t in enumerate(targets_to_process, start=1):
                future = executor.submit(_process_company_with_retry, t, company_index, total_companies, ctx)
                future_to_target[future] = t

            completed_count = 0
            for future in as_completed(future_to_target):
                t = future_to_target[future]
                code = t["code"]
                company_name = t.get("_resolved_company_name", code)
                completed_count += 1

                result, error = future.result()
                if result is not None:
                    _write_single_result(result, t["_output_path"])
                    written_count += 1
                    print(f"[{written_count}/{total_companies}] Wrote: {t['_output_path']}")
                elif error:
                    failed_companies.append((code, company_name, error))

                del future_to_target[future]

                if completed_count % CACHE_SAVE_INTERVAL == 0:
                    save_caches(ctx)
                    ctx.web_addr.clear_transient_caches()
                    gc.collect()

        save_caches(ctx)

        if failed_companies:
            logger.warning("処理失敗企業: %d社", len(failed_companies))
            for code, name, reason in failed_companies:
                logger.warning("  %s %s: %s", code, name, reason)
    else:
        logger.info("処理対象がありません. すべて調査済みとしてスキップしました.")

    logger.info("ランキング生成開始")
    generate_ranking(input_dir=ctx.output_dir, browser=ctx.browser, pool=ctx.pool)

    _post_pipeline_cleanup(ctx.base_dir)


def _post_pipeline_cleanup(base_dir: str, keep_logs: int = 5) -> None:
    """Post-pipeline cleanup: merge patches, prune old logs, delete .bak files."""
    logger.info("パイプライン後クリーンアップ開始")

    # 1. Merge pending address patches
    try:
        merged = merge_patches_safe(
            patch_dir=PATCH_DIR,
            overrides_file=ADDRESS_OVERRIDES_PATH,
        )
        if merged:
            logger.info("アドレスパッチをマージ: %d件", merged)
    except Exception:
        logger.warning("アドレスパッチのマージに失敗", exc_info=True)

    # 2. Prune old log files (keep latest N)
    log_dir = os.path.join(base_dir, "data", "output", "run_logs")
    try:
        log_files = sorted(f for f in os.listdir(log_dir) if f.endswith(".log"))
        if len(log_files) > keep_logs:
            for lf in log_files[:-keep_logs]:
                os.remove(os.path.join(log_dir, lf))
                logger.info("古いログを削除: %s", lf)
    except Exception:
        logger.warning("ログファイルの整理に失敗", exc_info=True)

    # 3. Delete .bak files
    config_dir = os.path.join(base_dir, "config")
    try:
        for bf in os.listdir(config_dir):
            if bf.endswith(".bak"):
                os.remove(os.path.join(config_dir, bf))
                logger.info("バックアップを削除: %s", bf)
    except Exception:
        logger.warning(".bakファイルの削除に失敗", exc_info=True)

    logger.info("クリーンアップ完了")


if __name__ == "__main__":
    main()
