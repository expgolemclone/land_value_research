import csv
import os
import tempfile
import unittest

from src.geocode_tokyo import TokyoGeocoder


class TestTokyoGeocoderNoChome(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.oaza_path = os.path.join(self._tmpdir.name, "oaza.csv")
        self.gaiku_path = os.path.join(self._tmpdir.name, "gaiku.csv")

        with open(self.oaza_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["都道府県名", "市区町村名", "大字町丁目名", "緯度", "経度"],
            )
            w.writeheader()
            w.writerow(
                {
                    "都道府県名": "東京都",
                    "市区町村名": "中央区",
                    "大字町丁目名": "日本橋兜町",
                    "緯度": "35.670001",
                    "経度": "139.770001",
                }
            )
            w.writerow(
                {
                    "都道府県名": "東京都",
                    "市区町村名": "港区",
                    "大字町丁目名": "六本木三丁目",
                    "緯度": "35.660001",
                    "経度": "139.730001",
                }
            )

        with open(self.gaiku_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "都道府県名",
                    "市区町村名",
                    "大字・丁目名",
                    "街区符号・地番",
                    "代表フラグ",
                    "住居表示フラグ",
                    "緯度",
                    "経度",
                ],
            )
            w.writeheader()
            w.writerow(
                {
                    "都道府県名": "東京都",
                    "市区町村名": "中央区",
                    "大字・丁目名": "日本橋兜町",
                    "街区符号・地番": "11",
                    "代表フラグ": "1",
                    "住居表示フラグ": "1",
                    "緯度": "35.680001",
                    "経度": "139.780001",
                }
            )
            w.writerow(
                {
                    "都道府県名": "東京都",
                    "市区町村名": "港区",
                    "大字・丁目名": "六本木三丁目",
                    "街区符号・地番": "4",
                    "代表フラグ": "1",
                    "住居表示フラグ": "1",
                    "緯度": "35.665001",
                    "経度": "139.735001",
                }
            )

        self.geocoder = TokyoGeocoder(self.oaza_path, self.gaiku_path)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_geocode_bango_without_chome_hits_gaiku(self) -> None:
        lat, lon, level = self.geocoder.geocode("東京都中央区日本橋兜町11番5号")
        self.assertEqual(level, "gaiku")
        self.assertAlmostEqual(lat, 35.680001)
        self.assertAlmostEqual(lon, 139.780001)

    def test_geocode_hyphen_without_chome_hits_gaiku(self) -> None:
        lat, lon, level = self.geocoder.geocode("東京都中央区日本橋兜町11-5")
        self.assertEqual(level, "gaiku")
        self.assertAlmostEqual(lat, 35.680001)
        self.assertAlmostEqual(lon, 139.780001)

    def test_geocode_town_only_hits_oaza(self) -> None:
        lat, lon, level = self.geocoder.geocode("東京都中央区日本橋兜町")
        self.assertEqual(level, "oaza_chome")
        self.assertAlmostEqual(lat, 35.670001)
        self.assertAlmostEqual(lon, 139.770001)

    def test_existing_chome_hyphen_still_hits_gaiku(self) -> None:
        lat, lon, level = self.geocoder.geocode("東京都港区六本木3-4-33")
        self.assertEqual(level, "gaiku")
        self.assertAlmostEqual(lat, 35.665001)
        self.assertAlmostEqual(lon, 139.735001)


if __name__ == "__main__":
    unittest.main()
