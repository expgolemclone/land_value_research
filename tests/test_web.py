import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
from src.web import build_ranking_payload, export_ranking_json


def write_output_csv(path: Path) -> None:
    row = dict.fromkeys(OUTPUT_COLUMNS, "")
    row.update(
        {
            COL_CODE: "9999",
            COL_COMPANY_NAME: "テスト会社",
            COL_SITE_NAME: "東京都合計",
            COL_ESTIMATED_VALUE: "1000000000",
            COL_BOOK_VALUE: "500000000",
            COL_UNREALIZED_GAIN: "500000000",
            COL_MULT_RAW: "2.0",
            COL_MULT: "2.000",
            COL_MARKET_CAP: "10000000000",
            COL_RATIO_RAW: "0.1",
            COL_RATIO: "0.100",
        }
    )
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerow(row)


class TestWebPayload(unittest.TestCase):
    def test_build_ranking_payload_shape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            write_output_csv(base / "9999_output.csv")
            with (
                patch("src.web.connect_company_db") as connect_db,
                patch("src.web.load_company_directory", return_value={}),
                patch(
                    "formula_screening.web.compute_all_stock_metrics",
                    return_value={
                        "9999": {
                            "price": 1234,
                            "peg_trailing_5": None,
                            "peg_trailing_5_status": "non_positive_growth",
                            "peg_blended_5y_actual_2f": None,
                            "peg_blended_5y_actual_2f_status": "missing_input",
                            "has_preferred_shares": True,
                        }
                    },
                ),
            ):
                connect_db.return_value.close.return_value = None
                payload = build_ranking_payload(base)

        self.assertEqual(1, len(payload))
        self.assertEqual("9999", payload[0]["code"])
        self.assertEqual("テスト会社", payload[0]["name"])
        self.assertEqual(0.1, payload[0]["ratio"])
        self.assertEqual(1234, payload[0]["price"])
        self.assertEqual("non_positive_growth", payload[0]["peg_trailing_5_status"])
        self.assertEqual("missing_input", payload[0]["peg_blended_5y_actual_2f_status"])
        self.assertEqual("non_positive_growth", payload[0]["metrics"]["peg_trailing_5_status"])
        self.assertIs(True, payload[0]["metrics"]["has_preferred_shares"])

    def test_build_ranking_payload_accepts_string_input_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            write_output_csv(base / "9999_output.csv")
            with (
                patch("src.web.connect_company_db") as connect_db,
                patch("src.web.load_company_directory", return_value={}),
                patch("formula_screening.web.compute_all_stock_metrics", return_value={}),
            ):
                connect_db.return_value.close.return_value = None
                payload = build_ranking_payload(str(base))

        self.assertEqual("9999", payload[0]["code"])

    def test_export_ranking_json_writes_payload(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "ranking.json"
            with patch("src.web.build_ranking_payload", return_value=[{"code": "9999"}]):
                export_ranking_json(out, input_dir=Path(td))

            payload = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual([{"code": "9999"}], payload)


if __name__ == "__main__":
    unittest.main()
