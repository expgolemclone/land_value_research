import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from src import company_metadata_fallback
from src.network import urlopen_with_retry
from src.web_address_research import WebAddressResearcher


class _FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._data


class TestNetworkRetry(unittest.TestCase):
    def test_urlopen_with_retry_recovers(self) -> None:
        req = urllib.request.Request("https://example.com")
        with patch(
            "urllib.request.urlopen",
            side_effect=[urllib.error.URLError(OSError("temp down")), _FakeResponse(b"ok")],
        ) as mocked:
            body = urlopen_with_retry(req, timeout_sec=1, retries=2, backoff_sec=0.0)
        self.assertEqual(body, b"ok")
        self.assertEqual(mocked.call_count, 2)

    def test_urlopen_with_retry_non_transient_http_error(self) -> None:
        req = urllib.request.Request("https://example.com")
        err = urllib.error.HTTPError(
            url="https://example.com",
            code=404,
            msg="not found",
            hdrs=None,
            fp=None,
        )
        with patch("urllib.request.urlopen", side_effect=err) as mocked:
            with self.assertRaises(urllib.error.HTTPError):
                urlopen_with_retry(req, timeout_sec=1, retries=3, backoff_sec=0.0)
        self.assertEqual(mocked.call_count, 1)


class TestMetadataCache(unittest.TestCase):
    def tearDown(self) -> None:
        company_metadata_fallback._METADATA_CACHE.clear()

    def test_fetch_from_irbank_does_not_cache_transient_failure(self) -> None:
        company_metadata_fallback._METADATA_CACHE.clear()
        ir_html = "<h1>テスト株式会社（1234）のIR情報・決算資料</h1><dt>時価</dt><dd>100億円</dd>".encode()
        edinet_html = 'title="有価証券報告書 第1期" href="notes?f=S100ABCD"'.encode()
        with patch(
            "src.company_metadata_fallback.urlopen_with_retry",
            side_effect=[
                urllib.error.URLError(OSError("down")),
                urllib.error.URLError(OSError("down")),
                ir_html,
                edinet_html,
            ],
        ):
            first = company_metadata_fallback.fetch_from_irbank("1234")
            second = company_metadata_fallback.fetch_from_irbank("1234")
        self.assertEqual(first.company_name, "")
        self.assertEqual(second.company_name, "テスト株式会社")
        self.assertTrue(second.securities_report_pdf_url.endswith("/S100ABCD.pdf"))

    def test_fetch_from_irbank_accepts_alpha_suffix_code(self) -> None:
        """英字サフィックス付きコード(xxxA形式)がバリデーションを通過し、IRBank URLが正しく構築される."""
        company_metadata_fallback._METADATA_CACHE.clear()
        ir_html = "<h1>トライアル HD（141A）のIR情報・決算資料</h1><dt>時価</dt><dd>4933億円</dd>".encode()
        edinet_html = 'title="有価証券報告書 第11期" href="notes?f=S100WRQT"'.encode()
        with patch(
            "src.company_metadata_fallback.urlopen_with_retry",
            side_effect=[ir_html, edinet_html],
        ):
            result = company_metadata_fallback.fetch_from_irbank("141A")
        self.assertEqual(result.company_name, "トライアル HD")
        self.assertTrue(result.securities_report_pdf_url.endswith("/S100WRQT.pdf"))


class TestWebFetchFailureCache(unittest.TestCase):
    def test_web_address_fetch_failure_is_not_pinned(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            r = WebAddressResearcher(cache_dir=d, timeout_sec=1)
            body = "<html><body>東京都中央区日本橋1-2-3</body></html>".encode()
            with patch.object(
                r,
                "_fetch_bytes",
                side_effect=[urllib.error.URLError(OSError("down")), body],
            ) as mocked:
                first = r._extract_candidates_by_url("https://example.com/a")
                second = r._extract_candidates_by_url("https://example.com/a")
            self.assertEqual(first, [])
            self.assertIn("東京都中央区日本橋1-2-3", second)
            self.assertEqual(mocked.call_count, 2)


if __name__ == "__main__":
    unittest.main()
