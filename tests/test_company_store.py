import tempfile
import unittest
from pathlib import Path

from src.company_store import (
    connect_company_db,
    load_company_directory,
    load_company_name_map,
    load_company_record,
    merge_company_record,
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
                )
                conn.commit()

                self.assertEqual(record["company_name"], "テスト株式会社")
                self.assertEqual(record["securities_report_pdf_url"], "https://example.com/report.pdf")

                loaded = load_company_record(conn, "1234")
                self.assertEqual(loaded, record)

                directory = load_company_directory(conn)
                self.assertEqual(directory["1234"]["company_name"], "テスト株式会社")
                self.assertEqual(load_company_name_map(conn), {"1234": "テスト株式会社"})

                updated = merge_company_record(
                    conn,
                    "1234",
                    company_name="",
                    securities_report_pdf_url="",
                )
                self.assertEqual(updated["company_name"], "テスト株式会社")
                self.assertEqual(updated["securities_report_pdf_url"], "https://example.com/report.pdf")
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
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
