import tempfile
import unittest
from pathlib import Path

from rank_market_cap_ratio import collect_excluded_codes, collect_rank_rows, write_rank_markdown

CSV_HEADER = (
    "証券コード,企業名,事業所名,住所,住所取得元,住所取得元URL,住所解決レベル,土地面積(m2),"
    "地価単価(円/m2),地価単価補正係数,住所解像度補正係数,地価単価算出方法,基準用途区分,最近傍用途区分,"
    "公示点ID,公示点距離(m),k近傍ID,k近傍用途区分,k近傍距離(m),k近傍単価(円/m2),k近傍距離分散(m2),"
    "k近傍最遠距離(m),地価推定信頼度スコア,地価推定信頼度,異常値警告,推定土地時価(円),土地簿価(円),"
    "含み益(円),評価倍率(実値),評価倍率,時価総額(円),時価総額比(実値),時価総額比\n"
)


class TestRankMarketCapRatio(unittest.TestCase):
    def test_collect_excluded_codes_ignores_site_processing_error(self) -> None:
        excluded_rows = [
            {"証券コード": "9999", "理由コード": "SITE_PROCESSING_ERROR"},
            {"証券コード": "8888", "理由コード": "DUPLICATE_ADDRESS_LARGE_AREA"},
        ]
        excluded = collect_excluded_codes(excluded_rows)
        self.assertNotIn("9999", excluded)
        self.assertIn("8888", excluded)

    def test_collect_rank_rows_keeps_company_with_non_critical_excluded_reason(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            out_csv = base / "9999_output.csv"
            out_csv.write_text(
                CSV_HEADER + "9999,テスト会社,東京都合計,,,,,,,,,,,,,,,,,,,,,,,,1000000000,500000000,500000000,"
                "2.0,2.000,10000000000,0.1,0.100\n",
                encoding="utf-8",
            )
            rows = collect_rank_rows(base, {}, {"8888"})
            self.assertEqual(1, len(rows))
            self.assertEqual("9999", rows[0]["証券コード"])

    def test_write_rank_markdown_escapes_pipe(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "ranking.md"
            rows = [
                {
                    "証券コード": "9998",
                    "企業名": "A|B",
                    "有報PDF_URL": "",
                    "時価総額比": 0.1,
                    "推定土地時価(円)": "1000000000",
                    "時価総額(円)": "10000000000",
                    "土地簿価(円)": "500000000",
                    "含み益(円)": "500000000",
                    "住所解決タグ": "",
                    "タグ件数": 0,
                    "異常値警告": "",
                    "元ファイル": "9998_output.csv",
                }
            ]
            write_rank_markdown(rows, out)
            text = out.read_text(encoding="utf-8")
            self.assertIn("A\\|B", text)


if __name__ == "__main__":
    unittest.main()
