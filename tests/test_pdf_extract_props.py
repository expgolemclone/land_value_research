"""pdf_extract パース関数の property-based テスト.

検証する性質:
- _normalize_text: 冪等性
- _parse_number: 有効な数値文字列なら float が返る / ダッシュ系は None
- _parse_number: 結果が非負
- _book_multiplier: 出力は {1_000, 1_000_000} のいずれか
- _area_scale: 出力は {1.0, 1_000.0} のいずれか
- _extract_site_name: 出力は空文字列にならない (最低 "不明")
"""

import unittest

from hypothesis import given
from hypothesis import strategies as st

from src.pdf_extract import (
    _area_scale,
    _book_multiplier,
    _extract_site_name,
    _normalize_text,
    _parse_number,
)

DASH_CHARS = ["-", "－", "ー", "―", "─"]


class TestPdfExtractProperties(unittest.TestCase):
    """pdf_extract パース関数の property-based テスト."""

    @given(s=st.text(max_size=200))
    def test_normalize_text_idempotent(self, s: str) -> None:
        """_normalize_text を2回適用しても結果が変わらない."""
        once = _normalize_text(s)
        twice = _normalize_text(once)
        self.assertEqual(twice, once)

    @given(
        integer_part=st.integers(min_value=0, max_value=999_999_999),
        decimal_part=st.integers(min_value=0, max_value=99),
    )
    def test_parse_number_valid_returns_float(self, integer_part: int, decimal_part: int) -> None:
        """有効な数値文字列を渡すと float が返る."""
        s = f"{integer_part:,}.{decimal_part:02d}"
        result = _parse_number(s)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, float)

    @given(dash=st.sampled_from(DASH_CHARS))
    def test_parse_number_dash_returns_none(self, dash: str) -> None:
        """ダッシュ系文字のみの入力は None を返す."""
        self.assertIsNone(_parse_number(dash))

    @given(s=st.text(max_size=100))
    def test_parse_number_non_negative(self, s: str) -> None:
        """_parse_number が値を返す場合、その値は非負."""
        result = _parse_number(s)
        if result is not None:
            self.assertGreaterEqual(result, 0.0)

    @given(s=st.text(max_size=200))
    def test_book_multiplier_valid_values(self, s: str) -> None:
        """_book_multiplier の出力は 1000 か 1000000 のいずれか."""
        result = _book_multiplier(s)
        self.assertIn(result, {1_000, 1_000_000})

    @given(s=st.text(max_size=200))
    def test_area_scale_valid_values(self, s: str) -> None:
        """_area_scale の出力は 1.0 か 1000.0 のいずれか."""
        result = _area_scale(s)
        self.assertIn(result, {1.0, 1_000.0})

    @given(s=st.text(max_size=200))
    def test_extract_site_name_never_empty(self, s: str) -> None:
        """_extract_site_name は空文字列を返さない (最低でも '不明')."""
        result = _extract_site_name(s)
        self.assertGreater(len(result), 0)
