import tempfile
import unittest
from pathlib import Path

from run import CompanySkipError, _resolve_market_cap, load_targets


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


class TestLoadTargets(unittest.TestCase):
    def test_legacy_report_url_column_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.csv"
            legacy_col = "p" + "df_url"
            input_path.write_text(
                f"code,company_name,{legacy_col},market_cap\n1234,テスト,https://example.com/report,100\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                load_targets(str(input_path))


if __name__ == "__main__":
    unittest.main()
