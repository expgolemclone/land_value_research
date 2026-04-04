import unittest

from src.jp_address import (
    normalize_addr,
    num_to_kanji,
    parse_town_chome_block,
    split_tokyo_municipality,
)


class TestNumToKanji(unittest.TestCase):
    def test_zero(self) -> None:
        self.assertEqual(num_to_kanji(0), "零")

    def test_single_digits(self) -> None:
        self.assertEqual(num_to_kanji(1), "一")
        self.assertEqual(num_to_kanji(9), "九")

    def test_ten(self) -> None:
        self.assertEqual(num_to_kanji(10), "十")

    def test_teens(self) -> None:
        self.assertEqual(num_to_kanji(11), "十一")
        self.assertEqual(num_to_kanji(19), "十九")

    def test_tens(self) -> None:
        self.assertEqual(num_to_kanji(20), "二十")
        self.assertEqual(num_to_kanji(90), "九十")

    def test_compound(self) -> None:
        self.assertEqual(num_to_kanji(35), "三十五")
        self.assertEqual(num_to_kanji(99), "九十九")

    def test_out_of_range(self) -> None:
        with self.assertRaises(ValueError):
            num_to_kanji(100)
        with self.assertRaises(ValueError):
            num_to_kanji(-1)


class TestParseTownChomeBlock(unittest.TestCase):
    def test_chome_with_block(self) -> None:
        town, chome, block = parse_town_chome_block("東京都中央区日本橋1丁目15番3号")
        self.assertEqual(town, "日本橋")
        self.assertEqual(chome, 1)
        self.assertEqual(block, 15)

    def test_hyphen_format(self) -> None:
        town, chome, block = parse_town_chome_block("東京都港区六本木3-4-33")
        self.assertEqual(town, "六本木")
        self.assertEqual(chome, 3)
        self.assertEqual(block, 4)

    def test_banchi_without_chome(self) -> None:
        town, chome, block = parse_town_chome_block("東京都中央区日本橋兜町11番5号")
        self.assertEqual(town, "日本橋兜町")
        self.assertIsNone(chome)
        self.assertEqual(block, 11)

    def test_town_only(self) -> None:
        town, chome, block = parse_town_chome_block("東京都中央区日本橋兜町")
        self.assertEqual(town, "日本橋兜町")
        self.assertIsNone(chome)
        self.assertIsNone(block)

    def test_non_tokyo(self) -> None:
        # Non-Tokyo addresses: split_tokyo_municipality returns None for muni,
        # and the full address becomes rest. Since it matches the town-only
        # pattern (no digits), it returns the address as town.
        town, chome, block = parse_town_chome_block("大阪府大阪市北区")
        self.assertIsNotNone(town)
        self.assertIsNone(chome)
        self.assertIsNone(block)


class TestNormalizeAddr(unittest.TestCase):
    def test_fullwidth_digits(self) -> None:
        result = normalize_addr("東京都港区六本木３丁目")
        self.assertIn("3丁目", result)

    def test_kanji_number_chome(self) -> None:
        result = normalize_addr("東京都港区六本木三丁目")
        self.assertIn("3丁目", result)

    def test_strips_postal_code(self) -> None:
        result = normalize_addr("〒100-0005 東京都千代田区")
        self.assertNotIn("〒", result)

    def test_fullwidth_dash(self) -> None:
        result = normalize_addr("六本木３－４")
        self.assertIn("3-4", result)


class TestSplitTokyoMunicipality(unittest.TestCase):
    def test_ku(self) -> None:
        muni, rest = split_tokyo_municipality("東京都中央区日本橋")
        self.assertEqual(muni, "中央区")
        self.assertEqual(rest, "日本橋")

    def test_shi(self) -> None:
        muni, rest = split_tokyo_municipality("東京都八王子市元本郷町")
        self.assertEqual(muni, "八王子市")
        self.assertEqual(rest, "元本郷町")

    def test_non_tokyo(self) -> None:
        muni, rest = split_tokyo_municipality("大阪府大阪市")
        self.assertIsNone(muni)


if __name__ == "__main__":
    unittest.main()
