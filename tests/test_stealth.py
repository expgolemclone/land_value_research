from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestProxyPoolDirect:
    def test_get_returns_none(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool.direct()

        assert pool.get() is None

    def test_exhausted_is_true(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool.direct()

        assert pool.exhausted is True

    def test_report_failure_is_noop(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool.direct()

        pool.report_failure()

        assert pool.exhausted is True


class TestProxyPoolFromUrl:
    def test_get_returns_proxy_url(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool.from_url("http://1.2.3.4:8080")

        assert pool.get() == "http://1.2.3.4:8080"

    def test_strips_protocol_prefix(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool.from_url("https://5.6.7.8:3128")

        assert pool.get() == "http://5.6.7.8:3128"


class TestProxyPoolRotation:
    def test_rotate_cycles_through_proxies(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool(["1.1.1.1:80", "2.2.2.2:80", "3.3.3.3:80"])

        first: str | None = pool.get()
        pool.rotate()
        second: str | None = pool.get()

        assert first == "http://1.1.1.1:80"
        assert second == "http://2.2.2.2:80"

    def test_rotate_wraps_around(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool(["1.1.1.1:80", "2.2.2.2:80"])

        pool.rotate()
        pool.rotate()
        result: str | None = pool.get()

        assert result == "http://1.1.1.1:80"


class TestProxyPoolReportFailure:
    def test_removes_proxy_after_max_failures(self) -> None:
        from src.stealth import ProxyPool

        # max_failures=2: 1回目でローテーション、2回目は別プロキシ
        # 元のプロキシに戻ってから再度失敗させて除去を確認
        pool: ProxyPool = ProxyPool(["1.1.1.1:80", "2.2.2.2:80"])

        pool.report_failure()  # 1.1.1.1 fail=1, rotate to 2.2.2.2
        pool.report_failure()  # 2.2.2.2 fail=1, rotate to 1.1.1.1
        pool.report_failure()  # 1.1.1.1 fail=2 >= max_failures, removed

        assert pool.get() == "http://2.2.2.2:80"

    def test_exhausted_after_all_removed(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool(["1.1.1.1:80"])

        pool.report_failure()
        pool.report_failure()

        assert pool.exhausted is True
        assert pool.get() is None


class TestProxyPoolSplit:
    def test_round_robin_distribution(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool(["a:1", "b:2", "c:3", "d:4", "e:5"])

        sub_pools: list[ProxyPool] = pool.split(3)

        assert len(sub_pools) == 3
        assert sub_pools[0].get() == "http://a:1"
        assert sub_pools[1].get() == "http://b:2"
        assert sub_pools[2].get() == "http://c:3"

    def test_split_with_fewer_proxies_than_n(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool(["a:1"])

        sub_pools: list[ProxyPool] = pool.split(3)

        assert sub_pools[0].get() == "http://a:1"
        assert sub_pools[1].get() is None
        assert sub_pools[2].get() is None

    def test_split_zero_raises(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool(["a:1"])

        with pytest.raises(ValueError, match="n must be positive"):
            pool.split(0)


class TestProxyPoolRepr:
    def test_repr_shows_count(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool(["a:1", "b:2"])

        assert "2" in repr(pool)
        assert "ProxyPool" in repr(pool)


class _FakeSession:
    """Minimal stand-in for curl_cffi.requests.Session."""

    def __init__(self, impersonate: str = "") -> None:
        self.impersonate: str = impersonate
        self.headers: dict[str, str] = {}
        self.proxies: dict[str, str] = {}


class _FakeCffiRequests:
    Session = _FakeSession


def _mock_curl_cffi() -> dict[str, object]:
    """Build sys.modules entries that make ``from curl_cffi import requests`` resolve to _FakeCffiRequests."""
    fake_top: MagicMock = MagicMock()
    fake_top.requests = _FakeCffiRequests
    return {"curl_cffi": fake_top, "curl_cffi.requests": _FakeCffiRequests}


class TestCreateSession:
    def test_without_pool_returns_session(self) -> None:
        with patch.dict("sys.modules", _mock_curl_cffi()):
            from src.stealth import create_session

            session = create_session(None)

            assert session is not None
            assert "User-Agent" in session.headers

    def test_with_pool_sets_proxy(self) -> None:
        with patch.dict("sys.modules", _mock_curl_cffi()):
            from src.stealth import ProxyPool, create_session

            pool: ProxyPool = ProxyPool(["9.9.9.9:1234"])

            session = create_session(pool)

            assert session.proxies.get("http") == "http://9.9.9.9:1234"


class TestRandomDelay:
    def test_sleeps_within_range(self) -> None:
        with patch("src.stealth.time.sleep") as mock_sleep:
            from src.stealth import random_delay

            random_delay(1.0, 2.0)

            mock_sleep.assert_called_once()
            slept: float = mock_sleep.call_args[0][0]
            assert 1.0 <= slept <= 2.0


class TestRandomUa:
    def test_returns_string(self) -> None:
        from src.stealth import random_ua

        ua: str = random_ua()

        assert isinstance(ua, str)
        assert "Mozilla" in ua


class TestUrlOpenWithRetryProxy:
    def test_proxy_route_returns_content(self) -> None:
        import urllib.request

        from src.network import urlopen_with_retry
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool.direct()
        mock_resp = MagicMock(status_code=200, content=b"hello")

        with patch("src.stealth.create_session") as mock_cs:
            mock_cs.return_value.get.return_value = mock_resp
            req: urllib.request.Request = urllib.request.Request("https://example.com")

            body: bytes = urlopen_with_retry(req, timeout_sec=1, pool=pool)

        assert body == b"hello"

    def test_proxy_429_triggers_report_failure(self) -> None:
        import urllib.request

        from src.network import urlopen_with_retry
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool(["1.1.1.1:80", "2.2.2.2:80"])
        resp_429: MagicMock = MagicMock(status_code=429, content=b"")
        resp_ok: MagicMock = MagicMock(status_code=200, content=b"ok")
        resp_ok.raise_for_status = MagicMock()
        call_count: list[int] = [0]
        original_report = pool.report_failure

        def tracking_report() -> None:
            call_count[0] += 1
            original_report()

        pool.report_failure = tracking_report  # type: ignore[assignment]

        with patch("src.stealth.create_session") as mock_cs:
            mock_cs.return_value.get.side_effect = [resp_429, resp_ok]
            req: urllib.request.Request = urllib.request.Request("https://example.com")

            body: bytes = urlopen_with_retry(
                req, timeout_sec=1, retries=2, backoff_sec=0.0, pool=pool,
            )

        assert body == b"ok"
        assert call_count[0] == 1
