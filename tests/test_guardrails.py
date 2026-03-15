import unittest

from src.anomaly import (
    detect_critical_anomaly,
    should_accept_web_address,
)


class GuardrailTests(unittest.TestCase):
    def test_aggregate_site_disables_web_address(self) -> None:
        self.assertFalse(should_accept_web_address("本社他", 100))

    def test_web_address_score_boundary(self) -> None:
        self.assertFalse(should_accept_web_address("本社", 39))
        self.assertTrue(should_accept_web_address("本社", 40))

    def test_critical_anomaly_for_aggregate_web_gaiku(self) -> None:
        reasons = detect_critical_anomaly(
            site_name="本社他",
            address_source="web",
            geocode_level="gaiku",
            unit_price_yen_per_m2=1_000_000,
            land_area_m2=100.0,
            enable_high_unit_price_large_area=True,
        )
        self.assertTrue(any(code == "AGGREGATE_WEB_GAIKU" for code, _ in reasons))

    def test_critical_anomaly_high_unit_price_boundary(self) -> None:
        reasons_low = detect_critical_anomaly(
            site_name="本社",
            address_source="override",
            geocode_level="gaiku",
            unit_price_yen_per_m2=19_999_999,
            land_area_m2=5_000.0,
            enable_high_unit_price_large_area=True,
        )
        reasons_high = detect_critical_anomaly(
            site_name="本社",
            address_source="override",
            geocode_level="gaiku",
            unit_price_yen_per_m2=20_000_000,
            land_area_m2=5_000.0,
            enable_high_unit_price_large_area=True,
        )
        self.assertFalse(any(code == "HIGH_UNIT_PRICE_LARGE_AREA" for code, _ in reasons_low))
        self.assertTrue(any(code == "HIGH_UNIT_PRICE_LARGE_AREA" for code, _ in reasons_high))


if __name__ == "__main__":
    unittest.main()
