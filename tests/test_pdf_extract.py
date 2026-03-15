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

