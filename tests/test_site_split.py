import unittest

from src.company_config import SiteSplitEntry, expand_site_splits
from src.facility_extract import FacilityLand


class TestExpandSiteSplitsPassthrough(unittest.TestCase):
    def test_no_splits_passthrough(self) -> None:
        """When no split entries exist, sites are returned unchanged."""
        sites = [
            FacilityLand("本社", "東京都千代田区丸の内1-9-2", 1000.0, 500_000_000.0),
            FacilityLand("工場", "東京都大田区城南島2丁目6-1", 5000.0, 200_000_000.0),
        ]
        overrides = {"本社": "東京都千代田区丸の内1-9-2"}
        expanded, flat = expand_site_splits(sites, overrides)
        self.assertEqual(len(expanded), 2)
        self.assertEqual(expanded[0].site_name, "本社")
        self.assertEqual(expanded[1].site_name, "工場")
        self.assertEqual(flat, {"本社": "東京都千代田区丸の内1-9-2"})

    def test_empty_overrides(self) -> None:
        """Empty overrides returns sites unchanged."""
        sites = [FacilityLand("本社", "東京都千代田区丸の内1-9-2", 1000.0, 500_000_000.0)]
        expanded, flat = expand_site_splits(sites, {})
        self.assertEqual(len(expanded), 1)
        self.assertEqual(flat, {})


class TestExpandSiteSplitsBasic(unittest.TestCase):
    def test_basic_split(self) -> None:
        """One site is split into two sub-sites."""
        sites = [
            FacilityLand("本社他", "東京都港区芝5丁目", 27000.0, 3_000_000_000.0),
        ]
        overrides = {
            "本社他": [
                SiteSplitEntry(name="本社", address="東京都港区芝5丁目33-1", area_m2=5000.0, book_value_yen=None),
                SiteSplitEntry(
                    name="城南島倉庫", address="東京都大田区城南島2丁目6-1", area_m2=22000.0, book_value_yen=None
                ),
            ],
        }
        expanded, flat = expand_site_splits(sites, overrides)
        self.assertEqual(len(expanded), 2)
        self.assertEqual(expanded[0].site_name, "本社")
        self.assertEqual(expanded[0].location_short, "東京都港区芝5丁目33-1")
        self.assertAlmostEqual(expanded[0].land_area_m2, 5000.0)
        self.assertEqual(expanded[1].site_name, "城南島倉庫")
        self.assertAlmostEqual(expanded[1].land_area_m2, 22000.0)

    def test_non_split_site_preserved(self) -> None:
        """Sites without split entries are preserved in order."""
        sites = [
            FacilityLand("支店", "東京都新宿区西新宿1-1-1", 2000.0, 100_000_000.0),
            FacilityLand("本社他", "東京都港区芝5丁目", 27000.0, 3_000_000_000.0),
        ]
        overrides = {
            "支店": "東京都新宿区西新宿1丁目1-1",
            "本社他": [
                SiteSplitEntry(name="本社", address="東京都港区芝5丁目33-1", area_m2=5000.0),
                SiteSplitEntry(name="倉庫", address="東京都大田区城南島2丁目6-1", area_m2=22000.0),
            ],
        }
        expanded, flat = expand_site_splits(sites, overrides)
        self.assertEqual(len(expanded), 3)
        self.assertEqual(expanded[0].site_name, "支店")
        self.assertEqual(expanded[0].location_short, "東京都新宿区西新宿1-1-1")  # original location_short
        self.assertEqual(expanded[1].site_name, "本社")
        self.assertEqual(expanded[2].site_name, "倉庫")

    def test_unmatched_split_ignored(self) -> None:
        """Split entries for non-existent sites are ignored."""
        sites = [
            FacilityLand("支店", "東京都新宿区西新宿1-1-1", 2000.0, 100_000_000.0),
        ]
        overrides = {
            "本社他": [
                SiteSplitEntry(name="本社", address="東京都港区芝5丁目33-1", area_m2=5000.0),
            ],
        }
        expanded, flat = expand_site_splits(sites, overrides)
        self.assertEqual(len(expanded), 1)
        self.assertEqual(expanded[0].site_name, "支店")
        # flat_overrides still contains the unmatched split entry
        self.assertIn("本社", flat)


class TestExpandSiteSplitsFlatOverrides(unittest.TestCase):
    def test_flat_overrides_complete(self) -> None:
        """Flat overrides contain both string entries and expanded split entries."""
        sites = [
            FacilityLand("支店", "東京都新宿区西新宿1-1-1", 2000.0, 100_000_000.0),
            FacilityLand("本社他", "東京都港区芝5丁目", 27000.0, 3_000_000_000.0),
        ]
        overrides = {
            "支店": "東京都新宿区西新宿1丁目1番1号",
            "本社他": [
                SiteSplitEntry(name="本社", address="東京都港区芝5丁目33-1", area_m2=5000.0),
                SiteSplitEntry(name="倉庫", address="東京都大田区城南島2丁目6-1", area_m2=22000.0),
            ],
        }
        _, flat = expand_site_splits(sites, overrides)
        self.assertEqual(flat["支店"], "東京都新宿区西新宿1丁目1番1号")
        self.assertEqual(flat["本社"], "東京都港区芝5丁目33-1")
        self.assertEqual(flat["倉庫"], "東京都大田区城南島2丁目6-1")
        # split key ("本社他") should NOT be in flat overrides
        self.assertNotIn("本社他", flat)


class TestBookValueAllocation(unittest.TestCase):
    def test_book_value_proportional(self) -> None:
        """When all book_value_yen are None, distribute proportionally by area."""
        sites = [FacilityLand("本社他", "東京都港区", 27000.0, 2_700_000_000.0)]
        overrides = {
            "本社他": [
                SiteSplitEntry(name="本社", address="東京都港区芝5丁目33-1", area_m2=5000.0),
                SiteSplitEntry(name="倉庫", address="東京都大田区城南島2丁目6-1", area_m2=22000.0),
            ],
        }
        expanded, _ = expand_site_splits(sites, overrides)
        # 5000/27000 * 2_700_000_000 = 500_000_000
        self.assertAlmostEqual(expanded[0].land_book_value_yen, 500_000_000.0)
        # 22000/27000 * 2_700_000_000 = 2_200_000_000
        self.assertAlmostEqual(expanded[1].land_book_value_yen, 2_200_000_000.0)

    def test_book_value_all_specified(self) -> None:
        """When all book_value_yen are specified, use them as-is."""
        sites = [FacilityLand("本社他", "東京都港区", 27000.0, 2_700_000_000.0)]
        overrides = {
            "本社他": [
                SiteSplitEntry(
                    name="本社", address="東京都港区芝5丁目33-1", area_m2=5000.0, book_value_yen=1_000_000_000.0
                ),
                SiteSplitEntry(
                    name="倉庫", address="東京都大田区城南島2丁目6-1", area_m2=22000.0, book_value_yen=1_700_000_000.0
                ),
            ],
        }
        expanded, _ = expand_site_splits(sites, overrides)
        self.assertAlmostEqual(expanded[0].land_book_value_yen, 1_000_000_000.0)
        self.assertAlmostEqual(expanded[1].land_book_value_yen, 1_700_000_000.0)

    def test_book_value_partial(self) -> None:
        """Specified book_value_yen is used; remaining is distributed to unspecified entries."""
        sites = [FacilityLand("本社他", "東京都港区", 27000.0, 2_700_000_000.0)]
        overrides = {
            "本社他": [
                SiteSplitEntry(
                    name="本社", address="東京都港区芝5丁目33-1", area_m2=5000.0, book_value_yen=700_000_000.0
                ),
                SiteSplitEntry(name="倉庫A", address="東京都大田区城南島2丁目6-1", area_m2=12000.0),
                SiteSplitEntry(name="倉庫B", address="東京都江東区新木場1丁目", area_m2=10000.0),
            ],
        }
        expanded, _ = expand_site_splits(sites, overrides)
        self.assertAlmostEqual(expanded[0].land_book_value_yen, 700_000_000.0)
        # remaining = 2_700_000_000 - 700_000_000 = 2_000_000_000
        # 倉庫A: 12000/22000 * 2_000_000_000
        self.assertAlmostEqual(expanded[1].land_book_value_yen, 2_000_000_000.0 * 12000 / 22000, places=0)
        # 倉庫B: 10000/22000 * 2_000_000_000
        self.assertAlmostEqual(expanded[2].land_book_value_yen, 2_000_000_000.0 * 10000 / 22000, places=0)


class TestDuplicateSiteNameExpansion(unittest.TestCase):
    def test_duplicate_site_names_expanded_once(self) -> None:
        """When multiple sites share the same name, split entries are expanded only once."""
        sites = [
            FacilityLand("本社営業所", "東京都足立区", 1322.3, 358_000_000.0),
            FacilityLand("本社営業所", "東京都中央区", 761.3, 19_000_000.0),
        ]
        overrides = {
            "本社営業所": [
                SiteSplitEntry(name="本社営業所(北千住)", address="東京都足立区千住関屋町8-6", area_m2=1322.3),
                SiteSplitEntry(name="本社営業所(スリーディ)", address="東京都中央区銀座1-13-5", area_m2=761.3),
            ],
        }
        expanded, flat = expand_site_splits(sites, overrides)
        self.assertEqual(len(expanded), 2)
        self.assertEqual(expanded[0].site_name, "本社営業所(北千住)")
        self.assertEqual(expanded[1].site_name, "本社営業所(スリーディ)")
        # 簿価は合算 (358M + 19M = 377M) から面積比で按分
        total_book = 358_000_000.0 + 19_000_000.0
        self.assertAlmostEqual(
            expanded[0].land_book_value_yen, total_book * 1322.3 / (1322.3 + 761.3), places=0
        )

    def test_duplicate_with_non_split_sites(self) -> None:
        """Duplicate site names are merged for split; other sites are preserved."""
        sites = [
            FacilityLand("工場", "東京都大田区", 5000.0, 200_000_000.0),
            FacilityLand("本社", "東京都品川区", 165.0, 76_000_000.0),
            FacilityLand("本社", "東京都港区", 2321.0, 1_308_000_000.0),
        ]
        overrides = {
            "工場": "東京都大田区城南島2-6-1",
            "本社": [
                SiteSplitEntry(name="本社(品川)", address="東京都品川区西五反田8-1-1", area_m2=165.0),
                SiteSplitEntry(name="本社(港区)", address="東京都港区赤坂3-7-13", area_m2=2321.0),
            ],
        }
        expanded, flat = expand_site_splits(sites, overrides)
        self.assertEqual(len(expanded), 3)
        self.assertEqual(expanded[0].site_name, "工場")
        self.assertEqual(expanded[1].site_name, "本社(品川)")
        self.assertEqual(expanded[2].site_name, "本社(港区)")


if __name__ == "__main__":
    unittest.main()
