"""pdf_extract パース関数の property-based テスト.

検証する性質:
- _normalize_text: 冪等性
- _parse_number: 有効な数値文字列なら float が返る / ダッシュ系は None
- _parse_number: 結果が非負
- _book_multiplier: 出力は {1_000, 1_000_000} のいずれか
- _area_scale: 出力は {1.0, 1_000.0} のいずれか
- _extract_site_name: 出力は空文字列にならない (最低 "不明")
"""

from hypothesis import given
from hypothesis import strategies as st

from src.pdf_extract import (
    _area_scale,
    _book_multiplier,
    _extract_site_name,
    _normalize_text,
    _parse_number,
)

# --- _normalize_text: 冪等性 ---


@given(s=st.text(max_size=200))
def test_normalize_text_idempotent(s: str) -> None:
    """_normalize_text を2回適用しても結果が変わらない."""
    once = _normalize_text(s)
    twice = _normalize_text(once)
    assert twice == once


# --- _parse_number: 有効な数値文字列 → float ---


@given(
    integer_part=st.integers(min_value=0, max_value=999_999_999),
    decimal_part=st.integers(min_value=0, max_value=99),
)
def test_parse_number_valid_returns_float(integer_part: int, decimal_part: int) -> None:
    """有効な数値文字列を渡すと float が返る."""
    s = f"{integer_part:,}.{decimal_part:02d}"
    result = _parse_number(s)
    assert result is not None
    assert isinstance(result, float)


# --- _parse_number: ダッシュ系は None ---

DASH_CHARS = ["-", "－", "ー", "―", "─"]


@given(dash=st.sampled_from(DASH_CHARS))
def test_parse_number_dash_returns_none(dash: str) -> None:
    """ダッシュ系文字のみの入力は None を返す."""
    assert _parse_number(dash) is None


# --- _parse_number: 結果が非負 ---


@given(s=st.text(max_size=100))
def test_parse_number_non_negative(s: str) -> None:
    """_parse_number が値を返す場合、その値は非負."""
    result = _parse_number(s)
    if result is not None:
        assert result >= 0.0


# --- _book_multiplier: 出力は {1_000, 1_000_000} のいずれか ---


@given(s=st.text(max_size=200))
def test_book_multiplier_valid_values(s: str) -> None:
    """_book_multiplier の出力は 1000 か 1000000 のいずれか."""
    result = _book_multiplier(s)
    assert result in {1_000, 1_000_000}


# --- _area_scale: 出力は {1.0, 1_000.0} のいずれか ---


@given(s=st.text(max_size=200))
def test_area_scale_valid_values(s: str) -> None:
    """_area_scale の出力は 1.0 か 1000.0 のいずれか."""
    result = _area_scale(s)
    assert result in {1.0, 1_000.0}


# --- _extract_site_name: 空文字列にならない (最低 "不明") ---


@given(s=st.text(max_size=200))
def test_extract_site_name_never_empty(s: str) -> None:
    """_extract_site_name は空文字列を返さない (最低でも '不明')."""
    result = _extract_site_name(s)
    assert len(result) > 0
