import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.ranking_data import collect_rank_rows, markdown_to_html
from src.schema import (
    COL_BOOK_VALUE,
    COL_CODE,
    COL_COMPANY_NAME,
    COL_ESTIMATED_VALUE,
    COL_MARKET_CAP,
    COL_MULT,
    COL_MULT_RAW,
    COL_RATIO,
    COL_RATIO_RAW,
    COL_SITE_NAME,
    COL_UNREALIZED_GAIN,
    OUTPUT_COLUMNS,
)


def write_output_csv(path: Path, *, code: str, name: str, ratio: str) -> None:
    row = dict.fromkeys(OUTPUT_COLUMNS, "")
    row.update(
        {
            COL_CODE: code,
            COL_COMPANY_NAME: name,
            COL_SITE_NAME: "東京都合計",
            COL_ESTIMATED_VALUE: "1000000000",
            COL_BOOK_VALUE: "500000000",
            COL_UNREALIZED_GAIN: "500000000",
            COL_MULT_RAW: "2.0",
            COL_MULT: "2.000",
            COL_MARKET_CAP: "10000000000",
            COL_RATIO_RAW: ratio,
            COL_RATIO: f"{float(ratio):.3f}",
        }
    )
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerow(row)


class TestRankingData(unittest.TestCase):
    def test_collect_rank_rows_includes_all_companies(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            write_output_csv(base / "9999_output.csv", code="9999", name="テスト会社", ratio="0.1")
            rows = collect_rank_rows(base, {})

        self.assertEqual(1, len(rows))
        self.assertEqual("9999", rows[0]["code"])
        self.assertEqual("テスト会社", rows[0]["name"])
        self.assertEqual(0.1, rows[0]["ratio"])
        self.assertIn("confidence", rows[0])

    def test_collect_rank_rows_accepts_string_input_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            write_output_csv(base / "9999_output.csv", code="9999", name="テスト会社", ratio="0.1")
            rows = collect_rank_rows(str(base), {})

        self.assertEqual("9999", rows[0]["code"])

    def test_collect_rank_rows_uses_company_directory_for_placeholder_name(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            write_output_csv(base / "9998_output.csv", code="9998", name="9998", ratio="0.2")
            rows = collect_rank_rows(base, {"9998": {"company_name": "補完会社"}})

        self.assertEqual("補完会社", rows[0]["name"])

    def test_collect_rank_rows_sorts_by_ratio_descending(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            write_output_csv(base / "1000_output.csv", code="1000", name="A", ratio="0.1")
            write_output_csv(base / "2000_output.csv", code="2000", name="B", ratio="0.3")
            rows = collect_rank_rows(base, {})

        self.assertEqual(["2000", "1000"], [row["code"] for row in rows])

    def test_collect_rank_rows_reads_research_memo(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            docs = base / "docs"
            docs.mkdir()
            (docs / "9997.md").write_text("# Memo\n\n- checked", encoding="utf-8")
            write_output_csv(base / "9997_output.csv", code="9997", name="メモ会社", ratio="0.4")
            with patch("src.ranking_data.DOCS_DIR", docs):
                rows = collect_rank_rows(base, {})

        self.assertEqual("# Memo\n\n- checked", rows[0]["memo_markdown"])

    def test_markdown_to_html_escapes_special_chars(self) -> None:
        html = markdown_to_html("# A<B>&C\n\n- `x`")

        self.assertIn("A&lt;B&gt;&amp;C", html)
        self.assertIn("<code>x</code>", html)
        self.assertIn("<ul>", html)

    def test_markdown_to_html_rejects_unsafe_link_schemes(self) -> None:
        html = markdown_to_html("[unsafe](javascript:alert(1)) [safe](https://example.com)")

        self.assertNotIn("javascript:", html)
        self.assertIn('href="https://example.com"', html)


if __name__ == "__main__":
    unittest.main()
