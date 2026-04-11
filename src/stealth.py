"""Browser-profile session factory and rotating proxy pool.

Browser impersonation is provided by curl_cffi for direct-HTTP code paths that
do not go through ``src.browser.BrowserService`` (e.g. ``populate_company_master``).
"""

from __future__ import annotations

import random
import threading
import time

from src.config import MAGIC

_CHROMIUM_BASE_HEADERS: dict[str, str] = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9,ja;q=0.8",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}
_SAFARI_HEADERS: dict[str, str] = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9,ja-JP;q=0.8,ja;q=0.7",
    "Upgrade-Insecure-Requests": "1",
}


def _chromium_headers(brand: str, version: str, platform: str) -> dict[str, str]:
    return {
        **_CHROMIUM_BASE_HEADERS,
        "Sec-CH-UA": f'"{brand}";v="{version}", "Chromium";v="{version}", "Not-A.Brand";v="99"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": f'"{platform}"',
    }


BrowserProfile = tuple[str, str, dict[str, str]]

_BROWSER_PROFILES: list[BrowserProfile] = [
    (
        "chrome124",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        _chromium_headers("Google Chrome", "124", "Windows"),
    ),
    (
        "chrome124",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        _chromium_headers("Google Chrome", "124", "macOS"),
    ),
    (
        "chrome124",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        _chromium_headers("Google Chrome", "124", "Linux"),
    ),
    (
        "chrome120",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        _chromium_headers("Google Chrome", "120", "Windows"),
    ),
    (
        "chrome120",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        _chromium_headers("Google Chrome", "120", "macOS"),
    ),
    (
        "edge101",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/101.0.4951.64 Safari/537.36 Edg/101.0.1210.47",
        _chromium_headers("Microsoft Edge", "101", "Windows"),
    ),
    (
        "safari17_0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        _SAFARI_HEADERS,
    ),
    (
        "safari15_5",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/15.5 Safari/605.1.15",
        _SAFARI_HEADERS,
    ),
]


def random_ua() -> str:
    return random.choice(_BROWSER_PROFILES)[1]


def create_session(
    pool: ProxyPool | None = None,
) -> object:
    from curl_cffi import requests as cffi_requests

    if pool is not None:
        impersonate, ua, extra_headers = pool.profile
    else:
        impersonate, ua, extra_headers = random.choice(_BROWSER_PROFILES)

    session: cffi_requests.Session = cffi_requests.Session(impersonate=impersonate)
    session.headers["User-Agent"] = ua
    session.headers.update(extra_headers)

    if pool is not None:
        proxy_url: str | None = pool.get()
        if proxy_url:
            session.proxies = {"http": proxy_url, "https": proxy_url}

    return session


def random_delay(min_s: float | None = None, max_s: float | None = None) -> None:
    if min_s is None:
        min_s = float(MAGIC["scrape"]["delay_min"])
    if max_s is None:
        max_s = float(MAGIC["scrape"]["delay_max"])
    time.sleep(random.uniform(min_s, max_s))


class ProxyPool:
    """Rotating proxy pool with automatic failover.

    Proxies must be supplied explicitly via ``from_url`` or a direct constructor
    call; auto-fetching of public proxy lists has been removed because the
    validation burst saturates local NAT/conntrack tables.
    """

    def __init__(self, proxies: list[str]) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._proxies: list[str] = list(proxies)
        self._index: int = 0
        self._failures: dict[str, int] = {}
        self._max_failures: int = int(MAGIC["proxy"]["max_failures"])
        self._profile_idx: int = random.randrange(len(_BROWSER_PROFILES))

    @classmethod
    def from_url(cls, url: str) -> ProxyPool:
        addr: str = url.removeprefix("http://").removeprefix("https://")
        return cls([addr])

    @classmethod
    def direct(cls) -> ProxyPool:
        return cls([])

    def get(self) -> str | None:
        with self._lock:
            if not self._proxies:
                return None
            return f"http://{self._proxies[self._index % len(self._proxies)]}"

    @property
    def profile(self) -> BrowserProfile:
        with self._lock:
            return _BROWSER_PROFILES[self._profile_idx % len(_BROWSER_PROFILES)]

    def _rotate_locked(self) -> None:
        if self._proxies:
            self._index += 1
            self._profile_idx = random.randrange(len(_BROWSER_PROFILES))
            proxy_url: str = f"http://{self._proxies[self._index % len(self._proxies)]}"
            print(f"  Rotated to proxy: {proxy_url}", flush=True)

    def rotate(self) -> None:
        with self._lock:
            self._rotate_locked()

    def report_failure(self) -> None:
        with self._lock:
            if not self._proxies:
                return
            addr: str = self._proxies[self._index % len(self._proxies)]
            self._failures[addr] = self._failures.get(addr, 0) + 1
            if self._failures[addr] >= self._max_failures:
                print(f"  Proxy {addr} failed {self._max_failures} times, removing", flush=True)
                self._proxies = [p for p in self._proxies if p != addr]
                if self._proxies:
                    self._index = self._index % len(self._proxies)
            else:
                self._rotate_locked()

    @property
    def exhausted(self) -> bool:
        with self._lock:
            return len(self._proxies) == 0

    def split(self, n: int) -> list[ProxyPool]:
        if n <= 0:
            raise ValueError("n must be positive")
        with self._lock:
            buckets: list[list[str]] = [[] for _ in range(n)]
            for i, addr in enumerate(self._proxies):
                buckets[i % n].append(addr)
        return [ProxyPool(b) for b in buckets]

    def __repr__(self) -> str:
        with self._lock:
            count: int = len(self._proxies)
            current: str | None = (
                f"http://{self._proxies[self._index % count]}" if count else None
            )
        return f"ProxyPool(count={count}, current={current})"
