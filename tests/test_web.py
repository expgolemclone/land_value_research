import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

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
from src.web import build_ranking_payload, export_github_pages_json, export_ranking_json


def write_output_csv(
    path: Path,
    *,
    code: str = "9999",
    name: str = "テスト会社",
    ratio: str = "0.1",
) -> None:
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
        self.assertIn("fcf_yield_avg", payload[0])
        self.assertIn("croic", payload[0])

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

    def test_export_github_pages_json_writes_standard_and_screened_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            input_dir = base / "output"
            output_dir = base / "assets"
            screening_config = base / "screening.toml"
            with patch(
                "src.web.build_ranking_payload",
                side_effect=[
                    [{"code": "all"}],
                    [{"code": "screened"}],
                ],
            ) as build_payload:
                standard_path, screened_path = export_github_pages_json(
                    input_dir=input_dir,
                    output_dir=output_dir,
                    screening_config=screening_config,
                )

            standard_payload = json.loads(standard_path.read_text(encoding="utf-8"))
            screened_payload = json.loads(screened_path.read_text(encoding="utf-8"))

        self.assertEqual(output_dir / "ranking.json", standard_path)
        self.assertEqual(output_dir / "ranking_net_cash_fcf.json", screened_path)
        self.assertEqual([{"code": "all"}], standard_payload)
        self.assertEqual([{"code": "screened"}], screened_payload)
        build_payload.assert_has_calls(
            [
                call(input_dir, screening_config=None),
                call(input_dir, screening_config=screening_config),
            ]
        )

    def test_build_ranking_payload_filters_by_screening_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            strategy = base / "strategy.toml"
            strategy.write_text("[[filters]]\n", encoding="utf-8")
            config = base / "screening.toml"
            config.write_text(f'strategy_path = "{strategy}"\n', encoding="utf-8")
            write_output_csv(base / "9999_output.csv", code="9999", name="通過会社", ratio="0.2")
            write_output_csv(base / "8888_output.csv", code="8888", name="除外会社", ratio="0.3")
            with (
                patch("src.web.connect_company_db") as connect_db,
                patch("src.web.load_company_directory", return_value={}),
                patch(
                    "formula_screening.web.run_screening_strategy_payload",
                    return_value=[
                        {
                            "code": "9999",
                            "price": 2222,
                            "metrics": {
                                "net_cash_ratio": 0.5,
                                "per": 8.0,
                                "equity_ratio": 70.0,
                            },
                            "fcf_yield_avg": 0.04,
                            "croic": 0.03,
                            "peg_trailing_5": 1.2,
                            "peg_trailing_5_status": "ok",
                            "peg_blended_5y_actual_2f": None,
                            "peg_blended_5y_actual_2f_status": "missing_input",
                            "has_preferred_shares": False,
                        }
                    ],
                ) as run_strategy,
            ):
                connect_db.return_value.close.return_value = None
                payload = build_ranking_payload(base, screening_config=config)

        self.assertEqual(["9999"], [row["code"] for row in payload])
        self.assertEqual(2222, payload[0]["price"])
        self.assertEqual(0.5, payload[0]["metrics"]["net_cash_ratio"])
        self.assertEqual(0.04, payload[0]["fcf_yield_avg"])
        self.assertEqual(0.03, payload[0]["croic"])
        self.assertEqual(0.04, payload[0]["metrics"]["fcf_yield_avg"])
        self.assertFalse(payload[0]["metrics"]["has_preferred_shares"])
        run_strategy.assert_called_once_with(strategy, tickers=["8888", "9999"])


if __name__ == "__main__":
    unittest.main()
