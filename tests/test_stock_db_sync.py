import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from src.stock_db_sync import load_market_cap_from_stock_db, load_stock_db_xbrl_artifacts, run_stooq_scrape


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

        CREATE TABLE sec_reports (
            ticker TEXT NOT NULL,
            fiscal_year TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            doc_type TEXT NOT NULL DEFAULT 'annual_report',
            xbrl_path TEXT,
            source TEXT NOT NULL DEFAULT 'edinet',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (ticker, doc_id)
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


class TestLoadStockDbXbrlArtifacts(unittest.TestCase):
    def test_loads_latest_valid_xbrl_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "stocks.db"
            conn = _create_stock_db(db_path)
            try:
                old_artifact = root / "raw" / "xbrl" / "1234" / "S100OLD"
                old_artifact.mkdir(parents=True)
                (old_artifact / "report.xhtml").write_text("<html>old</html>", encoding="utf-8")
                (old_artifact.parent / "S100OLD.zip").write_bytes(b"oldzip")

                latest_artifact = root / "raw" / "xbrl" / "1234" / "S100NEW"
                latest_artifact.mkdir(parents=True)
                (latest_artifact / "report.xhtml").write_text("<html>new</html>", encoding="utf-8")
                (latest_artifact.parent / "S100NEW.zip").write_bytes(b"newzip")

                conn.executemany(
                    """
                    INSERT INTO sec_reports (
                        ticker, fiscal_year, doc_id, doc_type, xbrl_path, source, updated_at
                    )
                    VALUES (?, ?, ?, 'annual_report', ?, 'edinet', ?)
                    """,
                    [
                        ("1234", "FY2024", "S100OLD", str(old_artifact), "2026-04-01T00:00:00+00:00"),
                        ("1234", "latest", "S100NEW", str(latest_artifact), "2026-04-02T00:00:00+00:00"),
                    ],
                )
                conn.commit()

                result = load_stock_db_xbrl_artifacts(["1234"], db_path=db_path)

                artifact = result["1234"]
                self.assertEqual(artifact.doc_id, "S100NEW")
                self.assertEqual(artifact.xbrl_path, str(latest_artifact.resolve()))
                self.assertGreater(artifact.source_size, 0)
                self.assertGreater(artifact.source_mtime_ns, 0)
            finally:
                conn.close()

    def test_skips_artifact_without_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "stocks.db"
            conn = _create_stock_db(db_path)
            try:
                artifact = root / "raw" / "xbrl" / "1234" / "S100NOZIP"
                artifact.mkdir(parents=True)
                (artifact / "report.xhtml").write_text("<html>body</html>", encoding="utf-8")
                conn.execute(
                    """
                    INSERT INTO sec_reports (
                        ticker, fiscal_year, doc_id, doc_type, xbrl_path, source, updated_at
                    )
                    VALUES (?, 'latest', ?, 'annual_report', ?, 'edinet', ?)
                    """,
                    ("1234", "S100NOZIP", str(artifact), "2026-04-02T00:00:00+00:00"),
                )
                conn.commit()

                self.assertEqual(load_stock_db_xbrl_artifacts(["1234"], db_path=db_path), {})
            finally:
                conn.close()


class TestRunStooqScrape(unittest.TestCase):
    def test_returns_true_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.stock_db_sync.subprocess.run") as mock_run:
                import subprocess as sp

                mock_run.return_value = sp.CompletedProcess(
                    args=["uv", "run", "scrape-stooq-prices"],
                    returncode=0,
                    stdout="",
                    stderr="Imported 500 JP prices for 2026-04-30",
                )

                result = run_stooq_scrape(cwd=Path(tmpdir))

                self.assertTrue(result)
                mock_run.assert_called_once()
                call_kwargs = mock_run.call_args
                self.assertEqual(call_kwargs[1]["cwd"], tmpdir)

    def test_returns_false_on_nonzero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.stock_db_sync.subprocess.run") as mock_run:
                import subprocess as sp

                mock_run.return_value = sp.CompletedProcess(
                    args=["uv", "run", "scrape-stooq-prices"],
                    returncode=1,
                    stdout="",
                    stderr="Captcha error",
                )

                result = run_stooq_scrape(cwd=Path(tmpdir))

                self.assertFalse(result)

    def test_returns_false_on_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.stock_db_sync.subprocess.run") as mock_run:
                import subprocess as sp

                mock_run.side_effect = sp.TimeoutExpired(cmd="uv", timeout=300)

                result = run_stooq_scrape(cwd=Path(tmpdir))

                self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
