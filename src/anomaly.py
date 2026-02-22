from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TypedDict

from src.landprice_tokyo import PriceResult

# Use functional syntax because keys contain Japanese parentheses (e.g. "土地面積(m2)")
OutputRow = TypedDict(
    "OutputRow",
    {
        "証券コード": object,
        "企業名": object,
        "事業所名": object,
        "住所": object,
        "住所取得元": object,
        "住所取得元URL": object,
        "住所解決レベル": object,
        "土地面積(m2)": object,
        "地価単価(円/m2)": object,
        "地価単価補正係数": object,
        "住所解像度補正係数": object,
        "地価単価算出方法": object,
        "基準用途区分": object,
        "最近傍用途区分": object,
        "公示点ID": object,
        "公示点距離(m)": object,
        "k近傍ID": object,
        "k近傍用途区分": object,
        "k近傍距離(m)": object,
        "k近傍単価(円/m2)": object,
        "k近傍距離分散(m2)": object,
        "k近傍最遠距離(m)": object,
        "地価推定信頼度スコア": object,
        "地価推定信頼度": object,
        "異常値警告": object,
        "推定土地時価(円)": object,
        "土地簿価(円)": object,
        "含み益(円)": object,
        "評価倍率(実値)": object,
        "評価倍率": object,
        "時価総額(円)": object,
        "時価総額比(実値)": object,
        "時価総額比": object,
    },
)

WEB_ADDRESS_SCORE_MIN = 40
CRITICAL_UNIT_PRICE_YEN_PER_M2 = 20_000_000
CRITICAL_AREA_M2 = 5_000.0
CRITICAL_EVAL_MULTIPLE = 500.0
DUPLICATE_ADDRESS_WARNING_AREA_M2 = 50_000.0
DUPLICATE_ADDRESS_CRITICAL_AREA_M2 = 100_000.0
DUPLICATE_ADDRESS_CRITICAL_SITE_COUNT = 2
UNCERTAINTY_MAX_DIST_REF_M = 5_000.0
UNCERTAINTY_DIST_VAR_REF_M2 = 1_000_000.0
ANOMALY_MUNI_CENTROID_AREA_M2 = 10_000.0
ANOMALY_OAZA_CHOME_AREA_M2 = 50_000.0
ANOMALY_KNN_FAR_DIST_M = 10_000.0
ANOMALY_LOW_CONFIDENCE_AREA_M2 = 5_000.0


def calc_uncertainty_metrics(pr: PriceResult) -> tuple[float, float, float, str]:
    dists = [float(x) for x in pr.knn_dist_m] if pr.knn_dist_m else [float(pr.nearest_dist_m)]
    max_dist = float(max(dists)) if dists else 0.0
    if len(dists) <= 1:
        dist_var = 0.0
    else:
        mean = sum(dists) / len(dists)
        dist_var = sum((d - mean) * (d - mean) for d in dists) / len(dists)

    max_component = min(max_dist / UNCERTAINTY_MAX_DIST_REF_M, 1.0)
    var_component = min(dist_var / UNCERTAINTY_DIST_VAR_REF_M2, 1.0)
    score = max(0.0, min(1.0, 1.0 - (0.7 * max_component + 0.3 * var_component)))
    if score >= 0.67:
        label = "high"
    elif score >= 0.34:
        label = "medium"
    else:
        label = "low"
    return dist_var, max_dist, score, label


def detect_anomaly_warnings(
    land_area_m2: float,
    geocode_level: str,
    confidence_label: str,
    max_knn_dist_m: float,
    location_has_hoka: bool = False,
) -> list[str]:
    warnings: list[str] = []
    if location_has_hoka:
        warnings.append("所在地に「ほか」を含む(複数所在地の合算面積の可能性)")
    if geocode_level == "muni_centroid" and land_area_m2 >= ANOMALY_MUNI_CENTROID_AREA_M2:
        warnings.append("muni_centroidかつ土地面積10000m2以上")
    if geocode_level == "oaza_chome" and land_area_m2 >= ANOMALY_OAZA_CHOME_AREA_M2:
        warnings.append("oaza_chomeかつ土地面積50000m2以上")
    if max_knn_dist_m >= ANOMALY_KNN_FAR_DIST_M:
        warnings.append("k近傍最遠距離10000m以上")
    if confidence_label == "low" and land_area_m2 >= ANOMALY_LOW_CONFIDENCE_AREA_M2:
        warnings.append("信頼度lowかつ土地面積5000m2以上")
    return warnings


def is_aggregate_site_name(site_name: str) -> bool:
    normalized = re.sub(r"\s+", "", (site_name or ""))
    if not normalized:
        return False
    if "本社他" in normalized or normalized.startswith("本社・"):
        return True
    return normalized.endswith("他") or normalized.endswith("等")


def should_accept_web_address(site_name: str, score: int) -> bool:
    if is_aggregate_site_name(site_name):
        return False
    return score >= WEB_ADDRESS_SCORE_MIN


def detect_critical_anomaly(
    site_name: str,
    address_source: str,
    geocode_level: str,
    unit_price_yen_per_m2: int,
    land_area_m2: float,
    enable_high_unit_price_large_area: bool,
) -> list[tuple[str, str]]:
    reasons: list[tuple[str, str]] = []
    if is_aggregate_site_name(site_name) and address_source == "web" and geocode_level == "gaiku":
        reasons.append(
            (
                "AGGREGATE_WEB_GAIKU",
                "集約名拠点にweb由来の街区住所が採用されています.",
            )
        )
    if (
        enable_high_unit_price_large_area
        and unit_price_yen_per_m2 >= CRITICAL_UNIT_PRICE_YEN_PER_M2
        and land_area_m2 >= CRITICAL_AREA_M2
    ):
        reasons.append(
            (
                "HIGH_UNIT_PRICE_LARGE_AREA",
                "高単価かつ大面積のため過大評価リスクが高いです.",
            )
        )
    return reasons


@dataclass
class _DuplicateBucket:
    address: str
    total_area_m2: float = 0.0
    rows: list[OutputRow] = field(default_factory=list)


@dataclass(frozen=True)
class DuplicateHit:
    address: str
    count: int
    total_area_m2: float
    detail: str
    rows: list[OutputRow]


def detect_duplicate_address_large_area(
    site_rows: list[OutputRow],
) -> tuple[list[DuplicateHit], list[DuplicateHit]]:
    buckets: dict[str, _DuplicateBucket] = {}
    for row in site_rows:
        addr = str(row.get("住所", "") or "").strip()
        if not addr:
            continue
        area_raw = str(row.get("土地面積(m2)", "") or "").strip()
        if not area_raw:
            continue
        try:
            area = float(area_raw)
        except ValueError:
            continue
        b = buckets.get(addr)
        if b is None:
            b = _DuplicateBucket(address=addr)
            buckets[addr] = b
        b.total_area_m2 += area
        b.rows.append(row)

    warnings: list[DuplicateHit] = []
    criticals: list[DuplicateHit] = []
    for addr, b in buckets.items():
        count = len(b.rows)
        if count < DUPLICATE_ADDRESS_CRITICAL_SITE_COUNT:
            continue

        detail = f"同一住所に{count}拠点あります, 住所={addr}, 合計面積={b.total_area_m2:.2f}m2."
        hit = DuplicateHit(
            address=addr,
            count=count,
            total_area_m2=b.total_area_m2,
            detail=detail,
            rows=b.rows,
        )
        if b.total_area_m2 >= DUPLICATE_ADDRESS_WARNING_AREA_M2:
            warnings.append(hit)
        if b.total_area_m2 >= DUPLICATE_ADDRESS_CRITICAL_AREA_M2:
            criticals.append(hit)
    return warnings, criticals
