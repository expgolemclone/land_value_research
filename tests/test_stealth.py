from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


class TestProxyPoolDirect:
    def test_get_returns_none(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool.make_direct()

        assert pool.get() is None

    def test_exhausted_is_true(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool.make_direct()

        assert pool.exhausted is True

    def test_report_failure_is_noop(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool.make_direct()

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

        pool: ProxyPool = ProxyPool([("1.1.1.1:80", "http"), ("2.2.2.2:80", "http"), ("3.3.3.3:80", "http")])

        first: str | None = pool.get()
        pool.rotate()
        second: str | None = pool.get()

        assert first == "http://1.1.1.1:80"
        assert second == "http://2.2.2.2:80"

    def test_rotate_wraps_around(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool([("1.1.1.1:80", "http"), ("2.2.2.2:80", "http")])

        pool.rotate()
        pool.rotate()
        result: str | None = pool.get()

        assert result == "http://1.1.1.1:80"


class TestProxyPoolReportFailure:
    def test_removes_proxy_after_max_failures(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool([("1.1.1.1:80", "http"), ("2.2.2.2:80", "http")])

        pool.report_failure()  # 1.1.1.1 fail=1, rotate to 2.2.2.2
        pool.report_failure()  # 2.2.2.2 fail=1, rotate to 1.1.1.1
        pool.report_failure()  # 1.1.1.1 fail=2 >= max_failures, removed

        assert pool.get() == "http://2.2.2.2:80"

    def test_exhausted_after_all_removed(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool([("1.1.1.1:80", "http")])

        pool.report_failure()
        pool.report_failure()

        assert pool.exhausted is True
        assert pool.get() is None


class TestProxyPoolSplit:
    def test_round_robin_distribution(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool([("a:1", "http"), ("b:2", "http"), ("c:3", "http"), ("d:4", "http"), ("e:5", "http")])

        sub_pools: list[ProxyPool] = pool.split(3)

        assert len(sub_pools) == 3
        assert sub_pools[0].get() == "http://a:1"
        assert sub_pools[1].get() == "http://b:2"
        assert sub_pools[2].get() == "http://c:3"

    def test_split_with_fewer_proxies_than_n(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool([("a:1", "http")])

        sub_pools: list[ProxyPool] = pool.split(3)

        assert sub_pools[0].get() == "http://a:1"
        assert sub_pools[1].get() is None
        assert sub_pools[2].get() is None

    def test_split_zero_raises(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool([("a:1", "http")])

        with pytest.raises(ValueError, match="n must be positive"):
            pool.split(0)

    def test_split_propagates_direct_flag(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool([], direct=True)

        sub_pools: list[ProxyPool] = pool.split(2)

        assert sub_pools[0].direct is True
        assert sub_pools[1].direct is True


class TestProxyPoolRepr:
    def test_repr_shows_count(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool([("a:1", "http"), ("b:2", "http")])

        assert "2" in repr(pool)
        assert "ProxyPool" in repr(pool)


class TestProxyPoolSocks5:
    def test_from_url_socks5(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool.from_url("socks5://9.9.9.9:1080")

        assert pool.get() == "socks5h://9.9.9.9:1080"

    def test_from_url_socks5h(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool.from_url("socks5h://9.9.9.9:1080")

        assert pool.get() == "socks5h://9.9.9.9:1080"


class TestProxyPoolFromFile:
    def test_reads_host_port(self, tmp_path: Path) -> None:
        from src.stealth import ProxyPool

        proxy_file = tmp_path / "proxies.txt"
        proxy_file.write_text("1.1.1.1:8080\n2.2.2.2:3128\n")

        pool: ProxyPool = ProxyPool.from_file(proxy_file)

        assert pool.size == 2
        assert pool.get() == "http://1.1.1.1:8080"

    def test_reads_host_port_user_pass(self, tmp_path: Path) -> None:
        from src.stealth import ProxyPool

        proxy_file = tmp_path / "proxies.txt"
        proxy_file.write_text("1.1.1.1:8080:user:pass\n")

        pool: ProxyPool = ProxyPool.from_file(proxy_file)

        assert pool.get() == "http://user:pass@1.1.1.1:8080"

    def test_skips_blank_lines(self, tmp_path: Path) -> None:
        from src.stealth import ProxyPool

        proxy_file = tmp_path / "proxies.txt"
        proxy_file.write_text("\n1.1.1.1:8080\n\n")

        pool: ProxyPool = ProxyPool.from_file(proxy_file)

        assert pool.size == 1


class TestProxyPoolDirectFlag:
    def test_direct_pool_has_flag(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool.make_direct()

        assert pool.direct is True

    def test_non_direct_pool_has_no_flag(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool.from_url("http://1.2.3.4:8080")

        assert pool.direct is False


class TestProxyPoolSize:
    def test_size_returns_count(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool([("a:1", "http"), ("b:2", "http")])

        assert pool.size == 2

    def test_size_zero_for_direct(self) -> None:
        from src.stealth import ProxyPool

        pool: ProxyPool = ProxyPool.make_direct()

        assert pool.size == 0


class TestRandomDelay:
    def test_sleeps_within_range(self) -> None:
        with patch("stock_db.proxy_pool.time.sleep") as mock_sleep:
            from src.stealth import random_delay

            random_delay(1.0, 2.0)

            mock_sleep.assert_called_once()
            slept: float = mock_sleep.call_args[0][0]
            assert 1.0 <= slept <= 2.0
