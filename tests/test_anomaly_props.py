"""anomaly モジュールの property-based テスト.

検証する性質:
- calc_uncertainty_metrics: confidence_score が [0, 1] 範囲内
- calc_uncertainty_metrics: label と score の整合性
- detect_anomaly_warnings: 返り値が list[str]
- is_aggregate_site_name: bool を返す / 空文字列で例外にならない
- should_accept_web_address: aggregate なら常に False / score < 40 なら False
"""

from hypothesis import given
from hypothesis import strategies as st

from src.anomaly import (
    calc_uncertainty_metrics,
    detect_anomaly_warnings,
    is_aggregate_site_name,
    should_accept_web_address,
)
from src.landprice_tokyo import PriceResult

# --- PriceResult 生成用ストラテジー ---

price_results = st.builds(
    PriceResult,
    unit_price=st.integers(min_value=1, max_value=50_000_000),
    nearest_id=st.just("13-001-001"),
    nearest_dist_m=st.floats(min_value=0.0, max_value=50_000.0),
    knn_ids=st.lists(st.just("13-001-001"), min_size=1, max_size=5),
    knn_dist_m=st.lists(st.floats(min_value=0.0, max_value=50_000.0), min_size=1, max_size=5),
    knn_prices=st.lists(st.integers(min_value=1, max_value=50_000_000), min_size=1, max_size=5),
)


# --- calc_uncertainty_metrics: confidence_score が [0, 1] 範囲内 ---


@given(pr=price_results)
def test_calc_uncertainty_metrics_score_range(pr: PriceResult) -> None:
    """confidence_score は 0 以上 1 以下."""
    _, _, score, _ = calc_uncertainty_metrics(pr)
    assert 0.0 <= score <= 1.0


# --- calc_uncertainty_metrics: label と score の整合性 ---


@given(pr=price_results)
def test_calc_uncertainty_metrics_label_consistency(pr: PriceResult) -> None:
    """score >= 0.67 なら high, 0.34 <= score < 0.67 なら medium, score < 0.34 なら low."""
    _, _, score, label = calc_uncertainty_metrics(pr)
    if score >= 0.67:
        assert label == "high"
    elif score >= 0.34:
        assert label == "medium"
    else:
        assert label == "low"


# --- detect_anomaly_warnings: 返り値が list[str] ---

GEOCODE_LEVELS = ["gaiku", "oaza_chome", "muni_centroid"]
CONFIDENCE_LABELS = ["high", "medium", "low"]


@given(
    land_area_m2=st.floats(min_value=0.0, max_value=1_000_000.0),
    geocode_level=st.sampled_from(GEOCODE_LEVELS),
    confidence_label=st.sampled_from(CONFIDENCE_LABELS),
    max_knn_dist_m=st.floats(min_value=0.0, max_value=100_000.0),
)
def test_detect_anomaly_warnings_returns_list_of_str(
    land_area_m2: float,
    geocode_level: str,
    confidence_label: str,
    max_knn_dist_m: float,
) -> None:
    """detect_anomaly_warnings は常に list[str] を返す."""
    result = detect_anomaly_warnings(land_area_m2, geocode_level, confidence_label, max_knn_dist_m)
    assert isinstance(result, list)
    for item in result:
        assert isinstance(item, str)


# --- is_aggregate_site_name: bool を返す / 空文字列で例外にならない ---


@given(s=st.text(max_size=100))
def test_is_aggregate_site_name_returns_bool(s: str) -> None:
    """is_aggregate_site_name は常に bool を返し、例外を投げない."""
    result = is_aggregate_site_name(s)
    assert isinstance(result, bool)


def test_is_aggregate_site_name_empty_no_error() -> None:
    """空文字列と None で例外にならない."""
    assert isinstance(is_aggregate_site_name(""), bool)
    assert isinstance(is_aggregate_site_name(None), bool)


# --- should_accept_web_address: aggregate なら常に False ---

AGGREGATE_NAMES = ["本社他", "本社・営業部", "東京支店他", "本社等", "工場他"]


@given(
    name=st.sampled_from(AGGREGATE_NAMES),
    score=st.integers(min_value=0, max_value=100),
)
def test_should_accept_web_address_aggregate_always_false(name: str, score: int) -> None:
    """集約名拠点は score に関係なく常に False."""
    assert should_accept_web_address(name, score) is False


# --- should_accept_web_address: score < 40 なら False ---


@given(
    name=st.text(min_size=1, max_size=20, alphabet=st.characters(categories=("L",))),
    score=st.integers(min_value=0, max_value=39),
)
def test_should_accept_web_address_low_score_false(name: str, score: int) -> None:
    """score が 40 未満なら常に False (集約名でない場合も)."""
    assert should_accept_web_address(name, score) is False
