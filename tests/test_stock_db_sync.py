import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from src.stock_db_sync import load_market_cap_from_stock_db


def _create_stock_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE stocks (
            ticker TEXT PRIMARY KEY,
            name TEXT,
            shares_outstanding INTEGER,
            securities_report_url TEXT
        );

        CREATE TABLE prices (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            close REAL,
            volume INTEGER,
            updated_at TEXT,
            PRIMARY KEY (ticker, date)
        );
        """
    )
    conn.commit()
    return conn


class TestLoadMarketCapFromStockDb(unittest.TestCase):
    def test_computes_market_cap_from_shares_and_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "stocks.db"
            conn = _create_stock_db(db_path)
            try:
                today = date.today().isoformat()
                conn.execute(
                    """
                    INSERT INTO stocks (ticker, name, shares_outstanding, securities_report_url)
                    VALUES (?, ?, ?, ?)
                    """,
                    ("1234", "テスト株式会社", 1_000_000, ""),
                )
                conn.execute(
                    """
                    INSERT INTO prices (ticker, date, close, volume, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    ("1234", today, 123.4, None, "2026-04-01T00:00:00+00:00"),
                )
                conn.commit()

                result = load_market_cap_from_stock_db(["1234"], db_path=db_path)

                self.assertEqual(result, {"1234": 123_400_000})
            finally:
                conn.close()

    def test_skips_stale_or_incomplete_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "stocks.db"
            conn = _create_stock_db(db_path)
            try:
                fresh_date = date.today().isoformat()
                stale_date = (date.today() - timedelta(days=8)).isoformat()
                updated_today = "2026-04-30T00:00:00+00:00"
                conn.executemany(
                    """
                    INSERT INTO stocks (ticker, name, shares_outstanding, securities_report_url)
                    VALUES (?, ?, ?, ?)
                    """,
                    [
                        ("1111", "Fresh", 2_000_000, ""),
                        ("2222", "Stale", 3_000_000, ""),
                        ("3333", "NoClose", 4_000_000, ""),
                        ("4444", "NoShares", None, ""),
                    ],
                )
                conn.executemany(
                    """
                    INSERT INTO prices (ticker, date, close, volume, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        ("1111", fresh_date, 10.0, None, "2026-04-01T00:00:00+00:00"),
                        ("2222", stale_date, 20.0, None, updated_today),
                        ("3333", fresh_date, None, None, updated_today),
                        ("4444", fresh_date, 30.0, None, updated_today),
                    ],
                )
                conn.commit()

                result = load_market_cap_from_stock_db(
                    ["1111", "2222", "3333", "4444"],
                    db_path=db_path,
                    max_age_days=7,
                )

                self.assertEqual(result, {"1111": 20_000_000})
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
