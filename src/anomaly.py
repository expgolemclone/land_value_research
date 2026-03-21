from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.landprice_tokyo import PriceResult
from src.schema import COL_ADDRESS, COL_LAND_AREA, OutputRow

WEB_ADDRESS_SCORE_MIN = 40
CRITICAL_EVAL_MULTIPLE = 500.0
DUPLICATE_ADDRESS_WARNING_AREA_M2 = 50_000.0
DUPLICATE_ADDRESS_CRITICAL_SITE_COUNT = 2
UNCERTAINTY_MAX_DIST_REF_M = 5_000.0
UNCERTAINTY_DIST_VAR_REF_M2 = 1_000_000.0


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
        warnings.append("所在地に複数所在地シグナルを含む(他/ほか/及び/等/外)(合算面積の可能性)")
    if geocode_level == "muni_centroid":
        warnings.append("muni_centroid")
    if geocode_level == "oaza_chome":
        warnings.append("oaza_chome")
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
) -> list[DuplicateHit]:
    buckets: dict[str, _DuplicateBucket] = {}
    for row in site_rows:
        addr = str(row.get(COL_ADDRESS, "") or "").strip()
        if not addr:
            continue
        area_raw = str(row.get(COL_LAND_AREA, "") or "").strip()
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
    return warnings
