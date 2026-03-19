import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import rank_market_cap_ratio
from rank_market_cap_ratio import collect_rank_rows, generate_ranking, write_rank_html
from src.schema import (
    COL_ANOMALY_WARNING,
    COL_BOOK_VALUE,
    COL_CODE,
    COL_COMPANY_NAME,
    COL_CONFIDENCE,
    COL_ESTIMATED_VALUE,
    COL_MARKET_CAP,
    COL_RATIO,
    COL_UNREALIZED_GAIN,
    OUTPUT_COLUMNS,
    RANK_COL_GEOCODE_TAG,
    RANK_COL_SOURCE_FILE,
    RANK_COL_TAG_COUNT,
)

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
            self.assertEqual("9999", rows[0][COL_CODE])
            self.assertIn(COL_CONFIDENCE, rows[0])

    def test_write_rank_html_escapes_special_chars(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "ranking.html"
            rows = [
                {
                    COL_CODE: "9998",
                    COL_COMPANY_NAME: "A<B>&C",
                    "有報PDF_URL": "",
                    COL_RATIO: 0.1,
                    COL_ESTIMATED_VALUE: "1000000000",
                    COL_MARKET_CAP: "10000000000",
                    COL_BOOK_VALUE: "500000000",
                    COL_UNREALIZED_GAIN: "500000000",
                    RANK_COL_GEOCODE_TAG: "",
                    RANK_COL_TAG_COUNT: 0,
                    COL_CONFIDENCE: "high",
                    COL_ANOMALY_WARNING: "",
                    RANK_COL_SOURCE_FILE: "9998_output.csv",
                }
            ]
            write_rank_html(rows, out)
            text = out.read_text(encoding="utf-8")
            self.assertIn("A&lt;B&gt;&amp;C", text)
            self.assertIn("<table>", text)
            self.assertIn("</html>", text)

    def test_open_file_windows_falls_back_to_cmd_start(self) -> None:
        with patch.object(rank_market_cap_ratio.sys, "platform", "win32"):
            with patch.object(
                rank_market_cap_ratio.os,
                "startfile",
                side_effect=OSError("assoc missing"),
                create=True,
            ):
                with patch.object(rank_market_cap_ratio.subprocess, "Popen") as popen:
                    opened = rank_market_cap_ratio._open_file(Path("data/ranking/ranking_market_cap_ratio.html"))

        self.assertTrue(opened)
        popen.assert_called_once()
        self.assertEqual(
            [
                "cmd",
                "/c",
                "start",
                "",
                str(Path("data/ranking/ranking_market_cap_ratio.html").resolve()),
            ],
            popen.call_args.args[0],
        )

    def test_open_file_logs_warning_when_all_methods_fail(self) -> None:
        with self.assertLogs("rank_market_cap_ratio", level="WARNING") as captured:
            with patch.object(rank_market_cap_ratio.sys, "platform", "win32"):
                with patch.object(
                    rank_market_cap_ratio.os,
                    "startfile",
                    side_effect=OSError("assoc missing"),
                    create=True,
                ):
                    with patch.object(
                        rank_market_cap_ratio.subprocess,
                        "Popen",
                        side_effect=OSError("start failed"),
                    ):
                        opened = rank_market_cap_ratio._open_file(Path("data/ranking/ranking_market_cap_ratio.html"))

        self.assertFalse(opened)
        self.assertTrue(any("ファイルを開けませんでした" in line for line in captured.output))

    def test_generate_ranking_skips_open_when_open_files_false(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            out_csv = base / "9999_output.csv"
            out_csv.write_text(
                CSV_HEADER + "9999,テスト会社,東京都合計,,,,,,,,,,,,,,,,,,,,,,,,1000000000,500000000,500000000,"
                "2.0,2.000,10000000000,0.1,0.100\n",
                encoding="utf-8",
            )
            out_html = base / "ranking.html"

            with patch.object(rank_market_cap_ratio, "_open_file") as open_file:
                generate_ranking(input_dir=base, output_path=out_html, open_files=False)

            self.assertTrue(out_html.exists())

        open_file.assert_not_called()


if __name__ == "__main__":
    unittest.main()
