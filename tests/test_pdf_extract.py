import unittest

from src.pdf_extract import (
    _area_scale,
    _book_multiplier,
    _extract_from_table,
    _extract_location,
    _extract_site_name,
    _normalize_text,
    _parse_land_area_cell,
    _parse_land_cell,
    _parse_number,
)


class TestNormalizeText(unittest.TestCase):
    def test_fullwidth_to_halfwidth(self) -> None:
        self.assertEqual(_normalize_text("１２３"), "123")

    def test_fullwidth_comma_and_period(self) -> None:
        self.assertEqual(_normalize_text("１，２３４．５"), "1,234.5")

    def test_fullwidth_parens(self) -> None:
        self.assertEqual(_normalize_text("（abc）"), "(abc)")

    def test_none_returns_empty(self) -> None:
        self.assertEqual(_normalize_text(None), "")

    def test_strips_whitespace(self) -> None:
        self.assertEqual(_normalize_text("  abc  "), "abc")


class TestParseNumber(unittest.TestCase):
    def test_plain_integer(self) -> None:
        self.assertAlmostEqual(_parse_number("123"), 123.0)

    def test_comma_separated(self) -> None:
        self.assertAlmostEqual(_parse_number("1,234,567"), 1234567.0)

    def test_decimal(self) -> None:
        self.assertAlmostEqual(_parse_number("12.5"), 12.5)

    def test_dash_returns_none(self) -> None:
        self.assertIsNone(_parse_number("-"))
        self.assertIsNone(_parse_number("－"))
        self.assertIsNone(_parse_number("ー"))

    def test_empty_returns_none(self) -> None:
        self.assertIsNone(_parse_number(""))
        self.assertIsNone(_parse_number(None))

    def test_fullwidth_number(self) -> None:
        self.assertAlmostEqual(_parse_number("２，３４５"), 2345.0)


class TestParseLandCell(unittest.TestCase):
    def test_land_with_area_in_parens(self) -> None:
        land, area = _parse_land_cell("5,000 (1,200)")
        self.assertAlmostEqual(land, 5000.0)
        self.assertAlmostEqual(area, 1200.0)

    def test_land_only(self) -> None:
        land, area = _parse_land_cell("3,000")
        self.assertAlmostEqual(land, 3000.0)
        self.assertIsNone(area)

    def test_empty(self) -> None:
        self.assertEqual(_parse_land_cell(""), (None, None))

    def test_annotation_brackets_stripped(self) -> None:
        land, area = _parse_land_cell("100 [注1] (50)")
        self.assertAlmostEqual(land, 100.0)
        self.assertAlmostEqual(area, 50.0)


class TestParseLandAreaCell(unittest.TestCase):
    def test_simple_number(self) -> None:
        self.assertAlmostEqual(_parse_land_area_cell("1,234"), 1234.0)

    def test_strips_annotation(self) -> None:
        self.assertAlmostEqual(_parse_land_area_cell("500 [注2]"), 500.0)

    def test_empty(self) -> None:
        self.assertIsNone(_parse_land_area_cell(""))


class TestExtractLocation(unittest.TestCase):
    def test_tokyo_ku(self) -> None:
        self.assertEqual(_extract_location("本社\n東京都中央区"), "東京都中央区")

    def test_prefecture_city(self) -> None:
        result = _extract_location("大阪府大阪市")
        self.assertIn("大阪府", result)
        self.assertIn("大阪市", result)

    def test_no_location(self) -> None:
        self.assertEqual(_extract_location("本社ビル"), "")

    def test_strips_trailing_ta(self) -> None:
        result = _extract_location("東京都港区他")
        self.assertEqual(result, "東京都港区")


class TestExtractSiteName(unittest.TestCase):
    def test_simple_name(self) -> None:
        self.assertEqual(_extract_site_name("本社"), "本社")

    def test_name_with_parens(self) -> None:
        self.assertEqual(_extract_site_name("本社（東京都中央区）"), "本社")

    def test_multiline(self) -> None:
        result = _extract_site_name("東京支店\n営業部")
        self.assertEqual(result, "東京支店営業部")

    def test_empty_returns_unknown(self) -> None:
        self.assertEqual(_extract_site_name(""), "不明")


class TestBookMultiplier(unittest.TestCase):
    def test_sen_en(self) -> None:
        self.assertEqual(_book_multiplier("事業所名 帳簿価額(千円)"), 1_000)

    def test_hyakuman_en(self) -> None:
        self.assertEqual(_book_multiplier("事業所名 帳簿価額(百万円)"), 1_000_000)

    def test_default(self) -> None:
        self.assertEqual(_book_multiplier("事業所名 帳簿価額"), 1_000_000)


class TestAreaScale(unittest.TestCase):
    def test_sen_m2(self) -> None:
        self.assertAlmostEqual(_area_scale("面積千㎡"), 1000.0)
        self.assertAlmostEqual(_area_scale("面積(千㎡)"), 1000.0)

    def test_m2(self) -> None:
        self.assertAlmostEqual(_area_scale("面積(㎡)"), 1.0)


class TestExtractFromTable(unittest.TestCase):
    def test_basic_table(self) -> None:
        table: list[list[str | None]] = [
            ["事業所名(所在地)", "土地", "面積"],
            ["本社\n東京都中央区", "100 (50)", "50"],
        ]
        results, errors = _extract_from_table(table)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].site_name, "本社")
        self.assertEqual(results[0].location_short, "東京都中央区")

    def test_empty_table(self) -> None:
        results, errors = _extract_from_table([])
        self.assertEqual(results, [])

    def test_no_data_rows(self) -> None:
        table: list[list[str | None]] = [
            ["事業所名(所在地)", "土地", "面積"],
        ]
        results, errors = _extract_from_table(table)
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
