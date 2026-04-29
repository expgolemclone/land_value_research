import unittest

from run import CompanySkipError, _resolve_market_cap


class TestResolveMarketCap(unittest.TestCase):
    def test_input_market_cap_takes_precedence(self) -> None:
        self.assertEqual(_resolve_market_cap("1234", 111, {"1234": 222}), 111)

    def test_stock_db_market_cap_is_used_when_input_missing(self) -> None:
        self.assertEqual(_resolve_market_cap("1234", None, {"1234": 222}), 222)

    def test_missing_market_cap_raises_refresh_hint(self) -> None:
        with self.assertRaises(CompanySkipError) as excinfo:
            _resolve_market_cap("1234", None, {})

        message = str(excinfo.exception)
        self.assertIn("時価総額が不足", message)
        self.assertIn("market_cap", message)


if __name__ == "__main__":
    unittest.main()
