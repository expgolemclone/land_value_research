import unittest
from pathlib import Path
from unittest.mock import patch

from src.stock_db_sync import (
    PriceRefreshError,
    StockDbCompanyMetadata,
    StockDbXbrlArtifact,
    load_market_cap_from_stock_db,
    load_stock_db_company_metadata,
    load_stock_db_xbrl_artifacts,
    refresh_stock_prices,
)


class TestLoadStockDbCompanyMetadata(unittest.TestCase):
    def test_loads_company_names_from_stock_db_bridge(self) -> None:
        with patch(
            "src.stock_db_sync.get_stock_names",
            return_value={"1234": "テスト株式会社", "9999": ""},
        ) as mock_get_stock_names:
            result = load_stock_db_company_metadata(["1234", "1234", "9999", ""])

        self.assertEqual(
            result,
            {"1234": StockDbCompanyMetadata(company_name="テスト株式会社")},
        )
        mock_get_stock_names.assert_called_once_with()

    def test_rejects_db_path_override(self) -> None:
        with self.assertRaises(ValueError):
            load_stock_db_company_metadata(["1234"], db_path=Path("/tmp/stocks.db"))


class TestLoadMarketCapFromStockDb(unittest.TestCase):
    def test_delegates_market_cap_lookup_to_stock_db_bridge(self) -> None:
        with patch(
            "src.stock_db_sync.get_stock_market_caps",
            return_value={"1234": 123_400_000},
        ) as mock_get_market_caps:
            result = load_market_cap_from_stock_db(
                ["1234", "1234", ""],
                max_age_days=3,
            )

        self.assertEqual(result, {"1234": 123_400_000})
        mock_get_market_caps.assert_called_once_with(["1234"], max_age_days=3)

    def test_returns_empty_without_api_call_for_empty_codes(self) -> None:
        with patch("src.stock_db_sync.get_stock_market_caps") as mock_get_market_caps:
            result = load_market_cap_from_stock_db(["", " "])

        self.assertEqual(result, {})
        mock_get_market_caps.assert_not_called()


class TestLoadStockDbXbrlArtifacts(unittest.TestCase):
    def test_loads_latest_xbrl_artifact_from_stock_db_bridge(self) -> None:
        with patch(
            "src.stock_db_sync.get_latest_xbrl_artifacts",
            return_value={
                "1234": {
                    "doc_id": "S100NEW",
                    "xbrl_path": "/tmp/raw/xbrl/1234/S100NEW",
                    "source_size": 123,
                    "source_mtime_ns": 456,
                }
            },
        ) as mock_get_artifacts:
            result = load_stock_db_xbrl_artifacts(["1234", "1234"])

        self.assertEqual(
            result,
            {
                "1234": StockDbXbrlArtifact(
                    doc_id="S100NEW",
                    xbrl_path="/tmp/raw/xbrl/1234/S100NEW",
                    source_size=123,
                    source_mtime_ns=456,
                )
            },
        )
        mock_get_artifacts.assert_called_once_with(["1234"])


class TestRefreshStockPrices(unittest.TestCase):
    def test_returns_true_on_success(self) -> None:
        with patch("src.stock_db_sync.ensure_prices_fresh", return_value=None) as mock_refresh:
            result = refresh_stock_prices()

        self.assertTrue(result)
        mock_refresh.assert_called_once_with()

    def test_returns_false_on_stock_db_error(self) -> None:
        with patch(
            "src.stock_db_sync.ensure_prices_fresh",
            side_effect=PriceRefreshError("Yahoo failed"),
        ):
            result = refresh_stock_prices()

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
