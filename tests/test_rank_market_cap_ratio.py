import tempfile
import unittest
from pathlib import Path

from rank_market_cap_ratio import collect_rank_rows, write_rank_html
from src.schema import OUTPUT_COLUMNS

CSV_HEADER = ",".join(OUTPUT_COLUMNS) + "\n"


class TestRankMarketCapRatio(unittest.TestCase):
    def test_collect_rank_rows_includes_all_companies(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            out_csv = base / "9999_output.csv"
            out_csv.write_text(
                CSV_HEADER + "9999,テスト会社,東京都合計,,,,,,,,,,,,,,,,,,,,,,,,1000000000,500000000,500000000,"
                "2.0,2.000,10000000000,0.1,0.100\n",
                encoding="utf-8",
            )
            rows = collect_rank_rows(base, {})
            self.assertEqual(1, len(rows))
            self.assertEqual("9999", rows[0]["証券コード"])
            self.assertIn("地価推定信頼度", rows[0])

    def test_write_rank_html_escapes_special_chars(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "ranking.html"
            rows = [
                {
                    "証券コード": "9998",
                    "企業名": "A<B>&C",
                    "有報PDF_URL": "",
                    "時価総額比": 0.1,
                    "推定土地時価(円)": "1000000000",
                    "時価総額(円)": "10000000000",
                    "土地簿価(円)": "500000000",
                    "含み益(円)": "500000000",
                    "住所解決タグ": "",
                    "タグ件数": 0,
                    "地価推定信頼度": "high",
                    "異常値警告": "",
                    "元ファイル": "9998_output.csv",
                }
            ]
            write_rank_html(rows, out)
            text = out.read_text(encoding="utf-8")
            self.assertIn("A&lt;B&gt;&amp;C", text)
            self.assertIn("<table>", text)
            self.assertIn("</html>", text)


if __name__ == "__main__":
    unittest.main()
