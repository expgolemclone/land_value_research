import argparse
import atexit
import csv
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
from datetime import datetime
from pathlib import Path
from typing import Any

from rank_market_cap_ratio import generate_ranking
from scripts.merge_address_patches import merge_patches_safe
from src.anomaly import (
    CRITICAL_AREA_M2,
    CRITICAL_EVAL_MULTIPLE,
    CRITICAL_UNIT_PRICE_YEN_PER_M2,
    DUPLICATE_ADDRESS_CRITICAL_AREA_M2,
    DUPLICATE_ADDRESS_CRITICAL_SITE_COUNT,
    OutputRow,
    calc_uncertainty_metrics,
    detect_anomaly_warnings,
    detect_critical_anomaly,
    detect_duplicate_address_large_area,
    should_accept_web_address,
)
from src.cache import load_json_dict, load_sites_cache, save_json_dict, save_sites_cache
from src.company_config import (
    SiteSplitEntry,
    expand_site_splits,
    load_address_overrides,
    load_company_master,
    load_market_caps,
    save_company_master,
)
from src.company_metadata_fallback import fetch_from_irbank
from src.geocode_tokyo import TokyoGeocoder
from src.landprice_tokyo import LandPriceTokyo, PriceResult
from src.network import is_transient_network_error
from src.pdf_extract import FacilityLand, extract_major_facilities_land
from src.utils import ensure_dir
from src.web_address_research import WebAddressResearcher
from src.web_cache import download_file, is_pdf_file

logger = logging.getLogger(__name__)

CACHE_SAVE_INTERVAL = 10
COMPANY_RETRY_COUNT = 3
COMPANY_RETRY_BASE_DELAY_SEC = 2.0

_print_lock = threading.Lock()


def _tprint(*args: object, **kwargs: object) -> None:
    """Thread-safe print wrapper."""
    with _print_lock:
        print(*args, **kwargs)


OUTPUT_FIELDNAMES = [
    "証券コード",
    "企業名",
    "事業所名",
    "住所",
    "住所取得元",
    "住所取得元URL",
    "住所解決レベル",
    "土地面積(m2)",
    "地価単価(円/m2)",
    "地価単価補正係数",
    "住所解像度補正係数",
    "地価単価算出方法",
    "基準用途区分",
    "最近傍用途区分",
    "公示点ID",
    "公示点距離(m)",
    "k近傍ID",
    "k近傍用途区分",
    "k近傍距離(m)",
    "k近傍単価(円/m2)",
    "k近傍距離分散(m2)",
    "k近傍最遠距離(m)",
    "地価推定信頼度スコア",
    "地価推定信頼度",
    "異常値警告",
    "推定土地時価(円)",
    "土地簿価(円)",
    "含み益(円)",
    "評価倍率(実値)",
    "評価倍率",
    "時価総額(円)",
    "時価総額比(実値)",
    "時価総額比",
]

EXCLUDED_FIELDNAMES = [
    "証券コード",
    "企業名",
    "事業所名",
    "理由コード",
    "理由詳細",
    "推定土地時価(円)",
    "土地簿価(円)",
    "時価総額比(実値)",
    "土地面積(m2)",
    "地価単価(円/m2)",
    "評価倍率(実値)",
    "閾値_地価単価(円/m2)",
    "閾値_土地面積(m2)",
    "閾値_評価倍率",
    "同一住所件数",
    "同一住所合計面積(m2)",
    "閾値_同一住所件数",
    "閾値_同一住所合計面積(m2)",
    "住所",
    "住所取得元",
    "住所解決レベル",
]


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
    company_master: dict[str, dict[str, Any]]
    addr_overrides: dict[str, dict[str, str | list[SiteSplitEntry]]]
    market_caps: dict[str, float]
    geocoder: TokyoGeocoder
    web_addr: WebAddressResearcher
    landprice: LandPriceTokyo
    price_cache_disk: dict[str, Any]
    geocode_cache_disk: dict[str, Any]
    geocode_cache: dict[str, tuple[float, float, str]]
    cache_lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class CompanyResult:
    code: str
    company_name: str
    out_rows: list[OutputRow]
    excluded_rows: list[dict[str, str]]
    is_critical: bool
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
    excluded_rows: list[dict[str, str]]
    is_critical: bool
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


def load_targets(input_path: str) -> list[dict[str, Any]]:
    rows = load_csv_rows(input_path)
    if not rows:
        return []

    header_map = {h.strip().lower(): i for i, h in enumerate(rows[0])}
    has_header = any(k in header_map for k in ["code", "証券コード", "コード"])
    targets: list[dict[str, Any]] = []

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
    return os.path.join(base_dir, "config", "input.csv")


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


def build_excluded_row(
    code: str,
    company_name: str,
    site_name: str,
    reason_code: str,
    reason_detail: str,
    est: str,
    book: str,
    mcap_ratio_raw: str,
    area_m2: str,
    unit_price: str,
    eval_multiple_raw: str,
    address: str,
    address_source: str,
    geocode_level: str,
    duplicate_count: str = "",
    duplicate_total_area: str = "",
) -> dict[str, str]:
    return {
        "証券コード": code,
        "企業名": company_name,
        "事業所名": site_name,
        "理由コード": reason_code,
        "理由詳細": reason_detail,
        "推定土地時価(円)": est,
        "土地簿価(円)": book,
        "時価総額比(実値)": mcap_ratio_raw,
        "土地面積(m2)": area_m2,
        "地価単価(円/m2)": unit_price,
        "評価倍率(実値)": eval_multiple_raw,
        "閾値_地価単価(円/m2)": str(CRITICAL_UNIT_PRICE_YEN_PER_M2),
        "閾値_土地面積(m2)": f"{CRITICAL_AREA_M2:.2f}",
        "閾値_評価倍率": f"{CRITICAL_EVAL_MULTIPLE:.3f}",
        "同一住所件数": duplicate_count,
        "同一住所合計面積(m2)": duplicate_total_area,
        "閾値_同一住所件数": str(DUPLICATE_ADDRESS_CRITICAL_SITE_COUNT) if duplicate_count else "",
        "閾値_同一住所合計面積(m2)": f"{DUPLICATE_ADDRESS_CRITICAL_AREA_M2:.2f}" if duplicate_count else "",
        "住所": address,
        "住所取得元": address_source,
        "住所解決レベル": geocode_level,
    }


def _setup_logging() -> None:
    log_dir = os.path.join(os.path.dirname(__file__), "docs")
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
    parser = argparse.ArgumentParser(description="東京都の土地推定時価を算出する")
    parser.add_argument("--input", default="")
    parser.add_argument("--output", default="data/output")
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
        "--enable-high-unit-price-large-area",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=("critical anomalyのHIGH_UNIT_PRICE_LARGE_AREA判定を有効化するか(default: off)"),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="企業レベル並列処理のワーカー数(default: 4, 1で逐次処理)",
    )
    return parser.parse_args()


def setup_environment(args: argparse.Namespace) -> RunContext:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_dir = os.path.join(base_dir, "config")
    data_dir = os.path.join(base_dir, "data")
    cache_dir = os.path.join(data_dir, "cache")
    ensure_dir(cache_dir)
    pdf_cache_dir = os.path.join(cache_dir, "pdf")
    ensure_dir(pdf_cache_dir)
    migrate_legacy_pdf_cache(cache_dir)
    facilities_cache_dir = os.path.join(cache_dir, "facilities_land")
    ensure_dir(facilities_cache_dir)
    price_cache_path = os.path.join(cache_dir, "price_result_cache.json")
    geocode_cache_path = os.path.join(cache_dir, "geocode_result_cache.json")

    company_master_path = os.path.join(config_dir, "company_master.yaml")
    company_master = load_company_master(company_master_path)
    addr_overrides = load_address_overrides(os.path.join(config_dir, "address_overrides.yaml"))
    market_caps = load_market_caps(os.path.join(config_dir, "market_cap_overrides.csv"))

    geocoder = TokyoGeocoder(
        oaza_csv=os.path.join(data_dir, "geocoding", "geocode_ref_oaza_chome_tokyo_2024", "13_2024.csv"),
        gaiku_csv=os.path.join(data_dir, "geocoding", "geocode_ref_gaiku_tokyo_2024", "13_2024.csv"),
    )
    web_addr = WebAddressResearcher(cache_dir=os.path.join(cache_dir, "web_address"))
    landprice = LandPriceTokyo(geojson_path=os.path.join(data_dir, "landprice", "tokyo_2025", "L01-25_13.geojson"))

    output_dir = resolve_path(base_dir, args.output)
    ensure_dir(output_dir)
    processed_lookup_dir = output_dir

    price_cache_disk = load_json_dict(price_cache_path)
    geocode_cache_disk = load_json_dict(geocode_cache_path)

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
        market_caps=market_caps,
        geocoder=geocoder,
        web_addr=web_addr,
        landprice=landprice,
        price_cache_disk=price_cache_disk,
        geocode_cache_disk=geocode_cache_disk,
        geocode_cache={},
    )
    atexit.register(save_caches, ctx)
    return ctx


def _filter_targets(
    targets: list[dict[str, Any]],
    ctx: RunContext,
) -> tuple[list[dict[str, Any]], list[tuple[str, str, str]]]:
    targets_to_process: list[dict[str, Any]] = []
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
    t: dict[str, Any],
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
        fallback = fetch_from_irbank(code)
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
            download_file(pdf_url, pdf_path)
        except (ValueError, urllib.error.URLError, OSError) as e:
            if is_transient_network_error(e):
                raise TransientNetworkError(f"証券コード{code}の有報PDF取得で一時通信エラー: {e}") from e
            raise CompanySkipError(f"証券コード{code}の有報PDF取得に失敗しました: {e}") from e

    sites_cache_path = os.path.join(ctx.facilities_cache_dir, f"{code}_sites.json")
    sites = load_sites_cache(sites_cache_path, pdf_path)
    if sites is None:
        sites = extract_major_facilities_land(pdf_path)
        save_sites_cache(sites_cache_path, pdf_path, sites)
    # サイト分割展開（tokyoフィルタ前に実施: 分割先が他県になるケースに対応）
    company_overrides = ctx.addr_overrides.get(code, {})
    if any(isinstance(v, list) for v in company_overrides.values()):
        sites, flat_overrides = expand_site_splits(sites, company_overrides)
        with ctx.cache_lock:
            ctx.addr_overrides[code] = flat_overrides
    tokyo_sites = [s for s in sites if s.location_short.startswith("東京都")]
    _tprint(f"[{company_index}/{total_companies}] 拠点: 全{len(sites)}件, 東京都対象{len(tokyo_sites)}件")

    mcap = t["market_cap"] if t["market_cap"] is not None else ctx.market_caps.get(code)
    if mcap is None and ctx.args.allow_auto_metadata:
        if fallback is None:
            fallback = fetch_from_irbank(code)
        if fallback.market_cap_yen is not None:
            mcap = fallback.market_cap_yen
    if mcap is None:
        raise CompanySkipError(
            f"証券コード{code}の時価総額が不足しています."
            " config/input.csvに market_cap を追加するか, market_cap_overrides.csvへ登録してください."
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
    """Geocode an address using 2-level cache (memory → disk → geocoder).

    Uses double-checked locking so that the heavy geocoder.geocode() call
    runs outside the lock, allowing other threads to proceed concurrently.
    """
    with ctx.cache_lock:
        geo = ctx.geocode_cache.get(full_addr)
        if geo is not None:
            return geo
        dg = ctx.geocode_cache_disk.get(full_addr)
        if isinstance(dg, list) and len(dg) == 3:
            geo = (float(dg[0]), float(dg[1]), str(dg[2]))
            ctx.geocode_cache[full_addr] = geo
            return geo

    # Compute outside lock — geocoder is thread-safe (Rust &self, no interior mutation)
    geo = ctx.geocoder.geocode(full_addr)

    with ctx.cache_lock:
        existing = ctx.geocode_cache.get(full_addr)
        if existing is not None:
            return existing
        ctx.geocode_cache_disk[full_addr] = [float(geo[0]), float(geo[1]), str(geo[2])]
        ctx.geocode_cache[full_addr] = geo
    return geo


def _deserialize_price_result(dp: dict[str, Any]) -> PriceResult:
    return PriceResult(
        unit_price=int(dp["unit_price"]),
        nearest_id=str(dp["nearest_id"]),
        nearest_dist_m=float(dp["nearest_dist_m"]),
        knn_ids=[str(x) for x in dp.get("knn_ids", [])],
        knn_dist_m=[float(x) for x in dp.get("knn_dist_m", [])],
        knn_prices=[int(x) for x in dp.get("knn_prices", [])],
    )


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
            if cand and should_accept_web_address(s.site_name, cand.score):
                full_addr = cand.address
                addr_source = "web"
                addr_source_url = cand.source_url

    if not full_addr:
        full_addr = s.location_short
        addr_source = "securities_report"

    lat, lon, geocode_level = _geocode_address(full_addr, ctx)

    target_landuse_kind = ""
    if ctx.args.landuse_match:
        seed_pr = ctx.landprice.nearest(lat=lat, lon=lon)
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
        anomaly_warnings.append("評価倍率閾値超過(単独では除外しない)")
    anomaly_text = " | ".join(anomaly_warnings)
    if anomaly_warnings:
        _tprint(
            f"Warn(anomaly): {code} {s.site_name} {geocode_level} "
            f"area={float(s.land_area_m2):.2f} warnings={anomaly_text}"
        )
    critical_reasons = detect_critical_anomaly(
        site_name=s.site_name,
        address_source=addr_source,
        geocode_level=geocode_level,
        unit_price_yen_per_m2=unit_price,
        land_area_m2=float(s.land_area_m2),
        enable_high_unit_price_large_area=ctx.args.enable_high_unit_price_large_area,
    )
    excluded_rows: list[dict[str, str]] = []
    is_critical = False
    if critical_reasons:
        is_critical = True
        for reason_code, reason_detail in critical_reasons:
            excluded_rows.append(
                build_excluded_row(
                    code=code,
                    company_name=company_name,
                    site_name=s.site_name,
                    reason_code=reason_code,
                    reason_detail=reason_detail,
                    est=str(est),
                    book=str(book),
                    mcap_ratio_raw=("" if mcap_ratio_raw is None else f"{mcap_ratio_raw:.12f}"),
                    area_m2=f"{float(s.land_area_m2):.2f}",
                    unit_price=str(unit_price),
                    eval_multiple_raw=("" if mult_raw is None else f"{mult_raw:.12f}"),
                    address=full_addr,
                    address_source=addr_source,
                    geocode_level=geocode_level,
                )
            )
        _tprint(f"Exclude(critical anomaly): {code} {s.site_name} reasons={'|'.join([x[0] for x in critical_reasons])}")

    out_row: dict[str, object] = {
        "証券コード": code,
        "企業名": company_name,
        "事業所名": s.site_name,
        "住所": full_addr,
        "住所取得元": addr_source,
        "住所取得元URL": addr_source_url,
        "住所解決レベル": geocode_level,
        "土地面積(m2)": f"{s.land_area_m2:.2f}",
        "地価単価(円/m2)": unit_price,
        "地価単価補正係数": f"{total_factor:.6f}",
        "住所解像度補正係数": f"{geocode_factor:.6f}",
        "地価単価算出方法": method,
        "基準用途区分": target_landuse_kind,
        "最近傍用途区分": nearest_landuse_kind,
        "公示点ID": pr.nearest_id,
        "公示点距離(m)": f"{pr.nearest_dist_m:.3f}",
        "k近傍ID": "|".join(pr.knn_ids),
        "k近傍用途区分": "|".join(knn_landuse_kinds),
        "k近傍距離(m)": "|".join([f"{d:.3f}" for d in pr.knn_dist_m]),
        "k近傍単価(円/m2)": "|".join([str(int(x)) for x in pr.knn_prices]),
        "k近傍距離分散(m2)": f"{dist_var:.3f}",
        "k近傍最遠距離(m)": f"{max_knn_dist_m:.3f}",
        "地価推定信頼度スコア": f"{confidence_score:.6f}",
        "地価推定信頼度": confidence_label,
        "異常値警告": anomaly_text,
        "推定土地時価(円)": est,
        "土地簿価(円)": book,
        "含み益(円)": profit,
        "評価倍率(実値)": ("" if mult_raw is None else f"{mult_raw:.12f}"),
        "評価倍率": ("" if mult_raw is None else f"{mult_raw:.3f}"),
        "時価総額(円)": int(mcap),
        "時価総額比(実値)": ("" if mcap_ratio_raw is None else f"{mcap_ratio_raw:.12f}"),
        "時価総額比": ("" if mcap_ratio_raw is None else f"{mcap_ratio_raw:.3f}"),
    }
    return _SiteResult(
        out_row=out_row,
        excluded_rows=excluded_rows,
        is_critical=is_critical,
        est=est,
        book=book,
        est_raw=est_raw,
        book_raw=book_raw,
    )


def _postprocess_duplicate_anomalies(
    code: str,
    company_name: str,
    out_rows: list[OutputRow],
) -> tuple[list[dict[str, str]], bool]:
    """Detect duplicate-address anomalies and return (excluded_rows, is_critical)."""
    duplicate_warnings, duplicate_criticals = detect_duplicate_address_large_area(out_rows)
    duplicate_address_count: dict[str, int] = {}
    duplicate_address_area: dict[str, float] = {}
    for row in out_rows:
        addr = str(row.get("住所", "") or "").strip()
        if not addr:
            continue
        duplicate_address_count[addr] = duplicate_address_count.get(addr, 0) + 1
        try:
            area = float(str(row.get("土地面積(m2)", "") or "0").replace(",", ""))
        except ValueError:
            area = 0.0
        duplicate_address_area[addr] = duplicate_address_area.get(addr, 0.0) + area

    for hit in duplicate_warnings:
        _tprint(f"Warn(anomaly): {code} duplicate_address {hit.detail}")
        for row in hit.rows:
            warning_label = "同一住所かつ大面積の複数拠点"
            old = str(row.get("異常値警告", "") or "").strip()
            row["異常値警告"] = f"{old} | {warning_label}" if old else warning_label

    excluded_rows: list[dict[str, str]] = []
    is_critical = False

    for row in out_rows:
        eval_multiple_raw: float | None = None
        eval_raw_str = str(row.get("評価倍率(実値)", "") or "").strip()
        if eval_raw_str:
            try:
                eval_multiple_raw = float(eval_raw_str.replace(",", ""))
            except ValueError:
                eval_multiple_raw = None
        row_geocode_level = str(row.get("住所解決レベル", "") or "").strip()
        addr = str(row.get("住所", "") or "").strip()
        duplicate_count = duplicate_address_count.get(addr, 0)
        is_coarse_geocode = row_geocode_level in {"muni_centroid", "oaza_chome"}
        if (
            eval_multiple_raw is not None
            and eval_multiple_raw >= CRITICAL_EVAL_MULTIPLE
            and is_coarse_geocode
            and duplicate_count >= DUPLICATE_ADDRESS_CRITICAL_SITE_COUNT
        ):
            is_critical = True
            excluded_rows.append(
                build_excluded_row(
                    code=code,
                    company_name=company_name,
                    site_name=str(row.get("事業所名", "") or ""),
                    reason_code="HIGH_EVAL_MULTIPLE_COMPOSITE",
                    reason_detail=(f"評価倍率閾値超過かつ住所解像度が粗く,同一住所に{duplicate_count}拠点あります."),
                    est=str(row.get("推定土地時価(円)", "") or ""),
                    book=str(row.get("土地簿価(円)", "") or ""),
                    mcap_ratio_raw=str(row.get("時価総額比(実値)", "") or ""),
                    area_m2=str(row.get("土地面積(m2)", "") or ""),
                    unit_price=str(row.get("地価単価(円/m2)", "") or ""),
                    eval_multiple_raw=str(row.get("評価倍率(実値)", "") or ""),
                    address=addr,
                    address_source=str(row.get("住所取得元", "") or ""),
                    geocode_level=row_geocode_level,
                    duplicate_count=str(duplicate_count),
                    duplicate_total_area=f"{duplicate_address_area.get(addr, 0.0):.2f}",
                )
            )

    if duplicate_criticals:
        is_critical = True
        for hit in duplicate_criticals:
            for row in hit.rows:
                excluded_rows.append(
                    build_excluded_row(
                        code=code,
                        company_name=company_name,
                        site_name=str(row.get("事業所名", "") or ""),
                        reason_code="DUPLICATE_ADDRESS_LARGE_AREA",
                        reason_detail=hit.detail,
                        est=str(row.get("推定土地時価(円)", "") or ""),
                        book=str(row.get("土地簿価(円)", "") or ""),
                        mcap_ratio_raw=str(row.get("時価総額比(実値)", "") or ""),
                        area_m2=str(row.get("土地面積(m2)", "") or ""),
                        unit_price=str(row.get("地価単価(円/m2)", "") or ""),
                        eval_multiple_raw=str(row.get("評価倍率(実値)", "") or ""),
                        address=str(row.get("住所", "") or ""),
                        address_source=str(row.get("住所取得元", "") or ""),
                        geocode_level=str(row.get("住所解決レベル", "") or ""),
                        duplicate_count=str(hit.count),
                        duplicate_total_area=f"{hit.total_area_m2:.2f}",
                    )
                )
        _tprint(f"Exclude(critical anomaly): {code} duplicate_address reasons=DUPLICATE_ADDRESS_LARGE_AREA")

    return excluded_rows, is_critical


def process_company(
    t: dict[str, Any],
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
    company_critical = False
    out_rows: list[OutputRow] = []
    excluded_rows: list[dict[str, str]] = []

    total_tokyo_sites = len(tokyo_sites)
    for site_index, s in enumerate(tokyo_sites, start=1):
        _tprint(f"[{company_index}/{total_companies}][{site_index}/{total_tokyo_sites}] 解析中: {code} {s.site_name}")
        try:
            sr = _process_site(code, company_name, s, mcap, cm.address_source_urls, ctx)
        except Exception as e:
            logger.warning("サイト処理スキップ: %s %s %s: %s", code, s.site_name, type(e).__name__, e)
            excluded_rows.append(
                build_excluded_row(
                    code=code,
                    company_name=company_name,
                    site_name=s.site_name,
                    reason_code="SITE_PROCESSING_ERROR",
                    reason_detail=f"{type(e).__name__}: {e}",
                    est="",
                    book=str(int(round(float(s.land_book_value_yen)))),
                    mcap_ratio_raw="",
                    area_m2=f"{float(s.land_area_m2):.2f}",
                    unit_price="",
                    eval_multiple_raw="",
                    address=s.location_short,
                    address_source="",
                    geocode_level="",
                )
            )
            continue
        out_rows.append(sr.out_row)
        excluded_rows.extend(sr.excluded_rows)
        if sr.is_critical:
            company_critical = True
        sum_est += sr.est
        sum_book += sr.book
        sum_est_raw += sr.est_raw
        sum_book_raw += sr.book_raw

    dup_excluded, dup_critical = _postprocess_duplicate_anomalies(code, company_name, out_rows)
    excluded_rows.extend(dup_excluded)
    if dup_critical:
        company_critical = True

    # 東京都合計行(東京都の対象が0件でも必ず出力する)
    profit = sum_est - sum_book
    mult_raw = (sum_est_raw / sum_book_raw) if not math.isclose(sum_book_raw, 0.0) else None
    mcap_ratio_raw = (sum_est_raw / float(mcap)) if mcap else None
    total_row = dict.fromkeys(OUTPUT_FIELDNAMES, "")
    total_row.update(
        {
            "証券コード": code,
            "企業名": company_name,
            "事業所名": "東京都合計",
            "地価単価算出方法": (
                (f"idw(k={ctx.args.k},p={ctx.args.p})" if ctx.args.price_method == "idw" else "nearest")
                + ("+landuse_match" if ctx.args.landuse_match else "")
            ),
            "推定土地時価(円)": sum_est,
            "土地簿価(円)": sum_book,
            "含み益(円)": profit,
            "評価倍率(実値)": ("" if mult_raw is None else f"{mult_raw:.12f}"),
            "評価倍率": ("" if mult_raw is None else f"{mult_raw:.3f}"),
            "時価総額(円)": int(mcap),
            "時価総額比(実値)": ("" if mcap_ratio_raw is None else f"{mcap_ratio_raw:.12f}"),
            "時価総額比": ("" if mcap_ratio_raw is None else f"{mcap_ratio_raw:.3f}"),
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
        excluded_rows=excluded_rows,
        is_critical=company_critical,
        sum_est=sum_est,
        tokyo_site_count=len(tokyo_sites),
    )


def write_results(
    results: list[CompanyResult],
    targets: list[dict[str, Any]],
    ctx: RunContext,
) -> None:
    total = len(targets)
    result_by_code: dict[str, CompanyResult] = {r.code: r for r in results}

    for write_index, t in enumerate(targets, start=1):
        code = t["code"]
        out_path = t["_output_path"]
        result = result_by_code.get(code)
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=OUTPUT_FIELDNAMES)
            w.writeheader()
            if result is not None:
                for r in result.out_rows:
                    w.writerow(r)
        print(f"[{write_index}/{total}] Wrote: {out_path}")

    all_excluded: list[dict[str, str]] = []
    for r in results:
        all_excluded.extend(r.excluded_rows)

    excluded_path = os.path.join(ctx.output_dir, "anomaly_excluded_companies.csv")
    with open(excluded_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=EXCLUDED_FIELDNAMES)
        w.writeheader()
        for r in all_excluded:
            w.writerow(r)
    print(f"Wrote: {excluded_path} ({len(all_excluded)} rows)")


def save_caches(ctx: RunContext) -> None:
    with ctx.cache_lock:
        save_json_dict(ctx.price_cache_path, ctx.price_cache_disk)
        save_json_dict(ctx.geocode_cache_path, ctx.geocode_cache_disk)
        save_company_master(ctx.company_master_path, ctx.company_master)
    ctx.web_addr.flush()


def _process_company_with_retry(
    t: dict[str, Any],
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


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    args = parse_args()
    _setup_logging()
    ctx = setup_environment(args)

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

        results: list[CompanyResult] = []
        failed_companies: list[tuple[str, str, str]] = []
        succeeded_targets: list[dict[str, Any]] = []

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
                    results.append(result)
                    succeeded_targets.append(t)
                elif error:
                    failed_companies.append((code, company_name, error))

                if completed_count % CACHE_SAVE_INTERVAL == 0:
                    save_caches(ctx)

        write_results(results, succeeded_targets, ctx)
        save_caches(ctx)

        if failed_companies:
            logger.warning("処理失敗企業: %d社", len(failed_companies))
            for code, name, reason in failed_companies:
                logger.warning("  %s %s: %s", code, name, reason)
    else:
        logger.info("処理対象がありません. すべて調査済みとしてスキップしました.")

    logger.info("ランキング生成開始")
    generate_ranking(input_dir=ctx.output_dir)

    _post_pipeline_cleanup(ctx.base_dir)


def _post_pipeline_cleanup(base_dir: str, keep_logs: int = 5) -> None:
    """Post-pipeline cleanup: merge patches, prune old logs, delete .bak files."""
    logger.info("パイプライン後クリーンアップ開始")

    config_dir = os.path.join(base_dir, "config")

    # 1. Merge pending address patches
    try:
        merged = merge_patches_safe(
            patch_dir=Path(os.path.join(config_dir, "address_patches")),
            overrides_file=Path(os.path.join(config_dir, "address_overrides.yaml")),
        )
        if merged:
            logger.info("アドレスパッチをマージ: %d件", merged)
    except Exception:
        logger.warning("アドレスパッチのマージに失敗", exc_info=True)

    # 2. Prune old log files (keep latest N)
    docs_dir = os.path.join(base_dir, "docs")
    try:
        log_files = sorted(f for f in os.listdir(docs_dir) if f.endswith(".log"))
        if len(log_files) > keep_logs:
            for lf in log_files[:-keep_logs]:
                os.remove(os.path.join(docs_dir, lf))
                logger.info("古いログを削除: %s", lf)
    except Exception:
        logger.warning("ログファイルの整理に失敗", exc_info=True)

    # 3. Delete .bak files
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
