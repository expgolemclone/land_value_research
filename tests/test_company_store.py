import tempfile
import unittest
from pathlib import Path

from src.company_store import (
    connect_company_db,
    load_company_directory,
    load_company_name_map,
    load_company_record,
    load_market_cap_snapshot,
    merge_company_record,
    save_market_cap_snapshot,
)


class TestCompanyStore(unittest.TestCase):
    def test_merge_company_record_persists_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "land.db"
            conn = connect_company_db(db_path)
            try:
                record = merge_company_record(
                    conn,
                    "1234",
                    company_name="テスト株式会社",
                    securities_report_pdf_url="https://example.com/report.pdf",
                    address_source_urls=["https://example.com/company"],
                )
                conn.commit()

                self.assertEqual(record["company_name"], "テスト株式会社")
                self.assertEqual(record["securities_report_pdf_url"], "https://example.com/report.pdf")
                self.assertEqual(record["address_source_urls"], ["https://example.com/company"])

                loaded = load_company_record(conn, "1234")
                self.assertEqual(loaded, record)

                directory = load_company_directory(conn)
                self.assertEqual(directory["1234"]["company_name"], "テスト株式会社")
                self.assertEqual(load_company_name_map(conn), {"1234": "テスト株式会社"})

                updated = merge_company_record(
                    conn,
                    "1234",
                    address_source_urls=[
                        "https://example.com/company",
                        "https://example.com/report",
                    ],
                )
                self.assertEqual(
                    updated["address_source_urls"],
                    ["https://example.com/company", "https://example.com/report"],
                )
            finally:
                conn.close()

    def test_market_cap_snapshot_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "land.db"
            conn = connect_company_db(db_path)
            try:
                save_market_cap_snapshot(conn, "5678", 123_456_789, "2026-04-28")
                conn.commit()

                snapshot = load_market_cap_snapshot(conn, "5678")
                self.assertIsNotNone(snapshot)
                assert snapshot is not None
                self.assertEqual(snapshot["market_cap_yen"], 123_456_789)
                self.assertEqual(snapshot["fetched_date"], "2026-04-28")
            finally:
                conn.close()

    def test_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "land.db"
            conn = connect_company_db(db_path)
            try:
                self.assertEqual(load_company_directory(conn), {})
                self.assertEqual(load_company_name_map(conn), {})
                self.assertEqual(load_company_record(conn, "0000"), {})
                self.assertIsNone(load_market_cap_snapshot(conn, "0000"))
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
