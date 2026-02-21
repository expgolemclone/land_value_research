"""jp_address モジュールの property-based テスト.

検証する性質:
- normalize_addr: 冪等性 (2回適用しても結果が変わらない)
- num_to_kanji: 往復性 (_kanji_to_int(num_to_kanji(n)) == n)
- num_to_kanji: 範囲外 (0-99 以外) で ValueError
- split_tokyo_municipality: 東京都プレフィクスがあれば muni が非 None
- build_oaza_chome_name: 出力が必ず「丁目」で終わる
"""

import unittest

from hypothesis import given
from hypothesis import strategies as st

from src.jp_address import (
    _kanji_to_int,
    build_oaza_chome_name,
    normalize_addr,
    num_to_kanji,
    split_tokyo_municipality,
)

TOKYO_MUNICIPALITIES = [
    "千代田区",
    "中央区",
    "港区",
    "新宿区",
    "文京区",
    "台東区",
    "墨田区",
    "江東区",
    "品川区",
    "目黒区",
    "大田区",
    "世田谷区",
    "渋谷区",
    "中野区",
    "杉並区",
    "豊島区",
    "北区",
    "荒川区",
    "板橋区",
    "練馬区",
    "足立区",
    "葛飾区",
    "江戸川区",
    "八王子市",
    "立川市",
    "武蔵野市",
    "三鷹市",
    "府中市",
    "調布市",
    "町田市",
    "小金井市",
    "日野市",
    "国分寺市",
    "国立市",
    "西東京市",
    "瑞穂町",
    "日の出町",
    "奥多摩町",
    "檜原村",
]


class TestJpAddressProperties(unittest.TestCase):
    """jp_address モジュールの property-based テスト."""

    @given(s=st.text(max_size=200))
    def test_normalize_addr_idempotent(self, s: str) -> None:
        """normalize_addr を2回適用しても結果が変わらない."""
        once = normalize_addr(s)
        twice = normalize_addr(once)
        self.assertEqual(twice, once)

    @given(n=st.integers(min_value=0, max_value=99))
    def test_num_to_kanji_roundtrip(self, n: int) -> None:
        """num_to_kanji で変換した漢字を _kanji_to_int で戻すと元の数値になる."""
        kanji = num_to_kanji(n)
        back = _kanji_to_int(kanji)
        self.assertEqual(back, n)

    @given(n=st.integers().filter(lambda x: x < 0 or x > 99))
    def test_num_to_kanji_out_of_range_raises(self, n: int) -> None:
        """0-99 範囲外の整数で ValueError が発生する."""
        with self.assertRaises(ValueError):
            num_to_kanji(n)

    @given(
        muni=st.sampled_from(TOKYO_MUNICIPALITIES),
        rest=st.text(alphabet=st.characters(categories=("L", "N")), max_size=30),
    )
    def test_split_tokyo_municipality_with_tokyo_prefix(self, muni: str, rest: str) -> None:
        """東京都+有効な区市町村で始まる住所は muni が非 None を返す."""
        addr = f"東京都{muni}{rest}"
        result_muni, _ = split_tokyo_municipality(addr)
        self.assertIsNotNone(result_muni)

    @given(
        town=st.text(min_size=1, max_size=20, alphabet=st.characters(categories=("L",))),
        chome=st.integers(min_value=1, max_value=99),
    )
    def test_build_oaza_chome_name_ends_with_chome(self, town: str, chome: int) -> None:
        """build_oaza_chome_name の出力は必ず「丁目」で終わる."""
        result = build_oaza_chome_name(town, chome)
        self.assertTrue(result.endswith("丁目"))
