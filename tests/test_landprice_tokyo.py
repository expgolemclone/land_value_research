import json
import os
import tempfile
import unittest

from src.landprice_tokyo import LandPriceTokyo


def _make_geojson(points: list[dict]) -> str:
    """Create a minimal GeoJSON with the given point data."""
    features = []
    for pt in points:
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [pt["lon"], pt["lat"]]},
                "properties": {
                    "L01_001": pt["l01_001"],
                    "L01_002": pt["l01_002"],
                    "L01_003": pt["l01_003"],
                    "L01_008": pt["price"],
                    "L01_051": pt.get("landuse", ""),
                },
            }
        )
    return json.dumps({"type": "FeatureCollection", "features": features})


class TestLandPriceTokyo(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        # Three points in central Tokyo area
        self.geojson_path = os.path.join(self._tmpdir.name, "test.geojson")
        geojson = _make_geojson(
            [
                {
                    "lat": 35.68,
                    "lon": 139.77,
                    "l01_001": "13",
                    "l01_002": "101",
                    "l01_003": "001",
                    "price": 1000000,
                    "landuse": "住宅",
                },
                {
                    "lat": 35.69,
                    "lon": 139.78,
                    "l01_001": "13",
                    "l01_002": "101",
                    "l01_003": "002",
                    "price": 2000000,
                    "landuse": "商業",
                },
                {
                    "lat": 35.70,
                    "lon": 139.79,
                    "l01_001": "13",
                    "l01_002": "101",
                    "l01_003": "003",
                    "price": 3000000,
                    "landuse": "商業",
                },
            ]
        )
        with open(self.geojson_path, "w", encoding="utf-8") as f:
            f.write(geojson)
        self.lp = LandPriceTokyo(self.geojson_path)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_nearest_returns_closest_point(self) -> None:
        # Query close to first point
        pr = self.lp.nearest(lat=35.6801, lon=139.7701)
        self.assertEqual(pr.unit_price, 1000000)
        self.assertEqual(pr.nearest_id, "13-101-001")

    def test_nearest_second_point(self) -> None:
        pr = self.lp.nearest(lat=35.6901, lon=139.7801)
        self.assertEqual(pr.unit_price, 2000000)
        self.assertEqual(pr.nearest_id, "13-101-002")

    def test_idw_returns_weighted_average(self) -> None:
        # Query between first and second point; IDW result should be between their prices
        pr = self.lp.idw(lat=35.685, lon=139.775, k=2, p=3, eps=1.0)
        self.assertGreater(pr.unit_price, 1000000)
        self.assertLess(pr.unit_price, 2000000)

    def test_idw_k1_equals_nearest(self) -> None:
        pr_idw = self.lp.idw(lat=35.6801, lon=139.7701, k=1)
        pr_near = self.lp.nearest(lat=35.6801, lon=139.7701)
        self.assertEqual(pr_idw.unit_price, pr_near.unit_price)

    def test_landuse_kind_filter(self) -> None:
        # Only 商業 points: should not return point 001 (住宅)
        pr = self.lp.nearest(lat=35.68, lon=139.77, landuse_kind="商業")
        self.assertIn("商業", self.lp.get_point_landuse_kind(pr.nearest_id))

    def test_landuse_kind_fallback(self) -> None:
        # Non-existent landuse falls back to all points
        pr = self.lp.nearest(lat=35.6801, lon=139.7701, landuse_kind="工業")
        self.assertEqual(pr.nearest_id, "13-101-001")

    def test_get_point_landuse_kind(self) -> None:
        self.assertEqual(self.lp.get_point_landuse_kind("13-101-001"), "住宅")
        self.assertEqual(self.lp.get_point_landuse_kind("13-101-002"), "商業")
        self.assertEqual(self.lp.get_point_landuse_kind("nonexistent"), "")

    def test_idw_invalid_k(self) -> None:
        with self.assertRaises(ValueError):
            self.lp.idw(lat=35.68, lon=139.77, k=0)


class TestLandPriceTokyoEmptyData(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.geojson_path = os.path.join(self._tmpdir.name, "empty.geojson")
        geojson = json.dumps({"type": "FeatureCollection", "features": []})
        with open(self.geojson_path, "w", encoding="utf-8") as f:
            f.write(geojson)
        self.lp = LandPriceTokyo(self.geojson_path)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_nearest_empty_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            self.lp.nearest(lat=35.68, lon=139.77)

    def test_idw_empty_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            self.lp.idw(lat=35.68, lon=139.77, k=3)


if __name__ == "__main__":
    unittest.main()
