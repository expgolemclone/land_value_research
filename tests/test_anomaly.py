import unittest

from src.anomaly import (
    calc_uncertainty_metrics,
    detect_anomaly_warnings,
    detect_duplicate_address_large_area,
    is_aggregate_site_name,
)
from src.schema import COL_ADDRESS, COL_LAND_AREA, COL_SITE_NAME
from src.landprice_tokyo import PriceResult


class TestCalcUncertaintyMetrics(unittest.TestCase):
    def test_close_distance_is_high(self) -> None:
        pr = PriceResult(
            unit_price=100000,
            nearest_id="13-001-001",
            nearest_dist_m=100.0,
            knn_ids=["13-001-001", "13-001-002", "13-001-003"],
            knn_dist_m=[100.0, 150.0, 200.0],
            knn_prices=[100000, 110000, 120000],
        )
        _, _, score, label = calc_uncertainty_metrics(pr)
        self.assertEqual(label, "high")
        self.assertGreaterEqual(score, 0.67)

    def test_far_distance_is_low(self) -> None:
        pr = PriceResult(
            unit_price=100000,
            nearest_id="13-001-001",
            nearest_dist_m=8000.0,
            knn_ids=["13-001-001", "13-001-002", "13-001-003"],
            knn_dist_m=[8000.0, 9000.0, 10000.0],
            knn_prices=[100000, 110000, 120000],
        )
        _, _, score, label = calc_uncertainty_metrics(pr)
        self.assertEqual(label, "low")
        self.assertLess(score, 0.34)

    def test_medium_distance(self) -> None:
        pr = PriceResult(
            unit_price=100000,
            nearest_id="13-001-001",
            nearest_dist_m=2000.0,
            knn_ids=["13-001-001", "13-001-002"],
            knn_dist_m=[2000.0, 3000.0],
            knn_prices=[100000, 110000],
        )
        _, _, score, label = calc_uncertainty_metrics(pr)
        self.assertEqual(label, "medium")

    def test_single_point(self) -> None:
        pr = PriceResult(
            unit_price=100000,
            nearest_id="13-001-001",
            nearest_dist_m=100.0,
            knn_ids=[],
            knn_dist_m=[],
            knn_prices=[],
        )
        dist_var, _, _, label = calc_uncertainty_metrics(pr)
        self.assertEqual(dist_var, 0.0)
        self.assertEqual(label, "high")


class TestDetectAnomalyWarnings(unittest.TestCase):
    def test_muni_centroid_large_area(self) -> None:
        warnings = detect_anomaly_warnings(
            land_area_m2=15000.0,
            geocode_level="muni_centroid",
            confidence_label="high",
            max_knn_dist_m=100.0,
        )
        self.assertTrue(any("muni_centroid" in w for w in warnings))

    def test_muni_centroid_small_area_no_warning(self) -> None:
        warnings = detect_anomaly_warnings(
            land_area_m2=5000.0,
            geocode_level="muni_centroid",
            confidence_label="high",
            max_knn_dist_m=100.0,
        )
        self.assertFalse(any("muni_centroid" in w for w in warnings))

    def test_oaza_chome_large_area(self) -> None:
        warnings = detect_anomaly_warnings(
            land_area_m2=60000.0,
            geocode_level="oaza_chome",
            confidence_label="high",
            max_knn_dist_m=100.0,
        )
        self.assertTrue(any("oaza_chome" in w for w in warnings))

    def test_knn_far_distance(self) -> None:
        warnings = detect_anomaly_warnings(
            land_area_m2=100.0,
            geocode_level="gaiku",
            confidence_label="high",
            max_knn_dist_m=15000.0,
        )
        self.assertTrue(any("k近傍" in w for w in warnings))

    def test_low_confidence_large_area(self) -> None:
        warnings = detect_anomaly_warnings(
            land_area_m2=6000.0,
            geocode_level="gaiku",
            confidence_label="low",
            max_knn_dist_m=100.0,
        )
        self.assertTrue(any("信頼度low" in w for w in warnings))

    def test_no_warnings(self) -> None:
        warnings = detect_anomaly_warnings(
            land_area_m2=100.0,
            geocode_level="gaiku",
            confidence_label="high",
            max_knn_dist_m=100.0,
        )
        self.assertEqual(warnings, [])


class TestIsAggregateSiteName(unittest.TestCase):
    def test_honsha_ta(self) -> None:
        self.assertTrue(is_aggregate_site_name("本社他"))

    def test_honsha_dot(self) -> None:
        self.assertTrue(is_aggregate_site_name("本社・営業部"))

    def test_ends_with_ta(self) -> None:
        self.assertTrue(is_aggregate_site_name("東京支店他"))

    def test_ends_with_tou(self) -> None:
        self.assertTrue(is_aggregate_site_name("本社等"))

    def test_simple_name_not_aggregate(self) -> None:
        self.assertFalse(is_aggregate_site_name("本社"))
        self.assertFalse(is_aggregate_site_name("東京支店"))

    def test_empty(self) -> None:
        self.assertFalse(is_aggregate_site_name(""))
        self.assertFalse(is_aggregate_site_name(None))


class TestDetectDuplicateAddressLargeArea(unittest.TestCase):
    def _make_row(self, addr: str, area: float) -> dict:
        return {COL_ADDRESS: addr, COL_LAND_AREA: f"{area:.2f}", COL_SITE_NAME: "テスト"}

    def test_no_duplicates(self) -> None:
        rows = [
            self._make_row("東京都中央区日本橋1-1", 1000.0),
            self._make_row("東京都港区六本木3-4", 2000.0),
        ]
        warnings = detect_duplicate_address_large_area(rows)
        self.assertEqual(len(warnings), 0)

    def test_duplicate_warning(self) -> None:
        rows = [
            self._make_row("東京都中央区", 30000.0),
            self._make_row("東京都中央区", 30000.0),
        ]
        warnings = detect_duplicate_address_large_area(rows)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].count, 2)
        self.assertAlmostEqual(warnings[0].total_area_m2, 60000.0)

    def test_single_site_not_flagged(self) -> None:
        rows = [self._make_row("東京都中央区", 200000.0)]
        warnings = detect_duplicate_address_large_area(rows)
        self.assertEqual(len(warnings), 0)


if __name__ == "__main__":
    unittest.main()
