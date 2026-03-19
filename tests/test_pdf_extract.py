"""Regression tests for PDF extraction helpers."""

from __future__ import annotations

import unittest

from src import pdf_extract


class TestExtractLocation(unittest.TestCase):
    def test_detects_hoka_after_closing_paren(self) -> None:
        loc, has_hoka = pdf_extract._extract_location("東京支店(東京都千代田区)他60営業所等")
        self.assertEqual(loc, "東京都千代田区")
        self.assertTrue(has_hoka)

    def test_no_false_positive_without_hoka(self) -> None:
        loc, has_hoka = pdf_extract._extract_location("本社(東京都千代田区丸の内一丁目4番1号)")
        self.assertEqual(loc, "東京都千代田区")
        self.assertFalse(has_hoka)


class TestExtractFromTable(unittest.TestCase):
    def test_skips_rental_table_without_land_column(self) -> None:
        table = [
            ["事業所名", "設備の内容", "床面積(㎡)", "年間賃借料(千円)"],
            ["(所在地)", "", "", ""],
            ["本社", "本社機能", "908.82", "86,008"],
            ["(東京都渋谷区)", "営業拠点", "", ""],
        ]

        rows, errs = pdf_extract._extract_from_table(table)

        self.assertEqual(rows, [])
        self.assertEqual(errs, [])

    def test_skips_table_without_land_column_even_if_numeric_parens_exist(self) -> None:
        table = [
            ["事業所名", "設備の内容", "合計", "従業員数"],
            ["(所在地)", "", "(千円)", "(名)"],
            ["本社\n(東京都渋谷区)", "事務所用設備", "232,009", "100(8)"],
        ]

        rows, errs = pdf_extract._extract_from_table(table)

        self.assertEqual(rows, [])
        self.assertEqual(errs, [])

    def test_extracts_land_row_with_explicit_land_column(self) -> None:
        table = [
            ["事業所名", "設備の内容", "土地", "合計"],
            ["(所在地)", "", "(百万円)(面積㎡)", "(百万円)"],
            ["本社\n(東京都江東区)", "その他設備", "407(190.1)", "680"],
        ]

        rows, errs = pdf_extract._extract_from_table(table)

        self.assertEqual(errs, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].site_name, "本社")
        self.assertEqual(rows[0].location_short, "東京都江東区")
        self.assertAlmostEqual(rows[0].land_area_m2, 190.1)
        self.assertEqual(rows[0].land_book_value_yen, 407_000_000)
