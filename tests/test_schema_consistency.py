"""Schema consistency tests.

These tests ensure that every consumer of column definitions stays in sync
with the single source of truth in src/schema.py.  If a column is added,
renamed, or reordered in schema.py and a downstream module is not updated,
one of these tests will fail.
"""

import unittest

from src.schema import EXCLUDED_COLUMNS, OUTPUT_COLUMNS, RANKING_COLUMNS, OutputRow


class TestOutputColumnsConsistency(unittest.TestCase):
    def test_output_row_keys_match_output_columns(self) -> None:
        """OutputRow TypedDict keys must equal OUTPUT_COLUMNS (same set, same order)."""
        row_keys = tuple(OutputRow.__annotations__)
        self.assertEqual(row_keys, OUTPUT_COLUMNS)

    def test_no_duplicate_output_columns(self) -> None:
        self.assertEqual(len(OUTPUT_COLUMNS), len(set(OUTPUT_COLUMNS)))

    def test_no_duplicate_excluded_columns(self) -> None:
        self.assertEqual(len(EXCLUDED_COLUMNS), len(set(EXCLUDED_COLUMNS)))

    def test_no_duplicate_ranking_columns(self) -> None:
        self.assertEqual(len(RANKING_COLUMNS), len(set(RANKING_COLUMNS)))

    def test_excluded_shared_columns_subset_of_output(self) -> None:
        """Columns shared between EXCLUDED and OUTPUT must exist in OUTPUT."""
        output_set = set(OUTPUT_COLUMNS)
        # These are EXCLUDED-only columns (anomaly metadata)
        excluded_only = {
            "理由コード",
            "理由詳細",
            "閾値_地価単価(円/m2)",
            "閾値_土地面積(m2)",
            "閾値_評価倍率",
            "同一住所件数",
            "同一住所合計面積(m2)",
            "閾値_同一住所件数",
            "閾値_同一住所合計面積(m2)",
        }
        shared = set(EXCLUDED_COLUMNS) - excluded_only
        missing = shared - output_set
        self.assertEqual(missing, set(), f"EXCLUDED columns not found in OUTPUT: {missing}")

    def test_ranking_column_count(self) -> None:
        """RANKING_COLUMNS must have exactly 15 entries."""
        self.assertEqual(len(RANKING_COLUMNS), 15)

    def test_output_column_count(self) -> None:
        """OUTPUT_COLUMNS must have exactly 33 entries."""
        self.assertEqual(len(OUTPUT_COLUMNS), 33)


class TestRunModuleUsesSchema(unittest.TestCase):
    def test_run_fieldnames_match_schema(self) -> None:
        """run.OUTPUT_FIELDNAMES must be derived from schema.OUTPUT_COLUMNS."""
        from run import EXCLUDED_FIELDNAMES, OUTPUT_FIELDNAMES

        self.assertEqual(tuple(OUTPUT_FIELDNAMES), OUTPUT_COLUMNS)
        self.assertEqual(tuple(EXCLUDED_FIELDNAMES), EXCLUDED_COLUMNS)


class TestRankModuleUsesSchema(unittest.TestCase):
    def test_write_rank_html_uses_ranking_columns(self) -> None:
        """write_rank_html headers should match RANKING_COLUMNS."""
        import tempfile
        from pathlib import Path

        from rank_market_cap_ratio import write_rank_html
        from src.schema import COL_CODE, COL_COMPANY_NAME, COL_RATIO

        row = {
            COL_CODE: "9999",
            COL_COMPANY_NAME: "テスト",
            "有報PDF_URL": "",
            COL_RATIO: 0.1,
            "推定土地時価(円)": "100",
            "時価総額(円)": "1000",
            "土地簿価(円)": "50",
            "含み益(円)": "50",
            "住所解決タグ": "",
            "調査済": "",
            "タグ件数": 0,
            "地価推定信頼度": "",
            "異常値警告": "",
            "元ファイル": "test.csv",
        }
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "test.html"
            write_rank_html([row], out)
            html_text = out.read_text(encoding="utf-8")

        # Extract <th> contents
        import re

        th_texts = re.findall(r"<th>(.*?)</th>", html_text)
        self.assertEqual(tuple(th_texts), RANKING_COLUMNS)


if __name__ == "__main__":
    unittest.main()
