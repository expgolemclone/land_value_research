"""Anti-detection HTTP infrastructure: proxy rotation, TLS fingerprint
mimicry, User-Agent rotation, and request throttling."""

from __future__ import annotations

import concurrent.futures
import random
import re
import threading
import time

import requests

from src.config import MAGIC

_HOST_PORT_RE: re.Pattern[str] = re.compile(
    r"^(\d{1,3}(?:\.\d{1,3}){3}):(\d{1,5})$",
)

_PROXY_SOURCES: list[str] = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    "https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/http.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt",
]

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

_ANON_CHECK_URLS: list[str] = [
    "https://httpbin.io/headers",
    "https://httpbin.org/headers",
]

_PROXY_LEAK_HEADERS: tuple[str, ...] = (
    "X-Forwarded-For",
    "Via",
    "X-Real-IP",
    "Forwarded",
    "X-Proxy-ID",
)

_CHECK_URLS: list[str] = [
    "https://finance.yahoo.com/quote/AAPL/",
    "https://www.investing.com/",
    "https://finance.yahoo.co.jp/",
    "https://www.google.com/",
    "https://www.amazon.com/",
    "https://www.microsoft.com/",
    "https://www.apple.com/",
    "https://github.com/",
    "https://www.bbc.com/",
    "https://www.theguardian.com/",
    "https://www.yahoo.co.jp/",
    "https://www.rakuten.co.jp/",
    "https://www.amazon.co.jp/",
    "https://www.ebay.com/",
    "https://www.walmart.com/",
    "https://www.spotify.com/",
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


def _fetch_proxy_candidates() -> list[str]:
    proxies: list[str] = []
    session: requests.Session = requests.Session()
    session.headers.update({"User-Agent": random_ua()})
    anon_timeout: int = int(MAGIC["proxy"]["anon_timeout"])

    for url in _PROXY_SOURCES:
        try:
            resp: requests.Response = session.get(url, timeout=anon_timeout)
            for line in resp.text.strip().splitlines():
                addr: str = line.strip()
                if not addr or addr.startswith("<"):
                    continue
                for prefix in ("http://", "https://"):
                    if addr.startswith(prefix):
                        addr = addr[len(prefix):]
                        break
                if _HOST_PORT_RE.match(addr):
                    proxies.append(addr)
        except requests.RequestException:
            continue

    random.shuffle(proxies)
    return proxies


def _check_proxy(
    addr: str,
    *,
    timeout: int | None = None,
    anon_timeout: int | None = None,
) -> str | None:
    if timeout is None:
        timeout = int(MAGIC["proxy"]["check_timeout"])
    if anon_timeout is None:
        anon_timeout = int(MAGIC["proxy"]["anon_timeout"])

    proxy_url: str = f"http://{addr}"
    ua: str = random_ua()
    proxies: dict[str, str] = {"http": proxy_url, "https": proxy_url}
    headers: dict[str, str] = {"User-Agent": ua}

    anon_passed: bool = False
    for anon_url in random.sample(_ANON_CHECK_URLS, len(_ANON_CHECK_URLS)):
        try:
            resp: requests.Response = requests.get(
                anon_url, proxies=proxies, headers=headers, timeout=anon_timeout,
            )
            if resp.status_code != 200:
                continue
            echoed: dict[str, str] = resp.json().get("headers", {})
            if any(echoed.get(h) for h in _PROXY_LEAK_HEADERS):
                return None
            anon_passed = True
            break
        except (requests.RequestException, ValueError):
            continue
    if not anon_passed:
        return None

    check_url: str = random.choice(_CHECK_URLS)
    try:
        resp = requests.get(
            check_url, proxies=proxies, headers=headers, timeout=timeout,
        )
        if resp.status_code == 200:
            return addr
    except requests.RequestException:
        pass
    return None


def fetch_live_proxies(
    *,
    target_count: int | None = None,
    check_workers: int | None = None,
    batch_size: int | None = None,
) -> list[str]:
    if target_count is None:
        target_count = int(MAGIC["proxy"]["target_count"])
    if check_workers is None:
        check_workers = int(MAGIC["proxy"]["check_workers"])
    if batch_size is None:
        batch_size = int(MAGIC["proxy"]["batch_size"])

    candidates: list[str] = _fetch_proxy_candidates()
    print(f"  {len(candidates)} proxy candidates, validating (anonymity + quality)...", flush=True)

    alive: list[str] = []
    for batch_start in range(0, len(candidates), batch_size):
        batch: list[str] = candidates[batch_start : batch_start + batch_size]
        executor: concurrent.futures.ThreadPoolExecutor = concurrent.futures.ThreadPoolExecutor(
            max_workers=check_workers,
        )
        futures: dict[concurrent.futures.Future[str | None], str] = {
            executor.submit(_check_proxy, addr): addr
            for addr in batch
        }
        try:
            for future in concurrent.futures.as_completed(futures):
                result: str | None = future.result()
                if result is not None:
                    alive.append(result)
                    if len(alive) % 10 == 0:
                        print(f"  ... {len(alive)} elite proxies so far", flush=True)
                    if len(alive) >= target_count:
                        break
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        if len(alive) >= target_count:
            break

    random.shuffle(alive)
    print(f"  {len(alive)} elite-anonymous proxies ready", flush=True)
    return alive


class ProxyPool:
    """Rotating proxy pool with automatic failover."""

    def __init__(self, proxies: list[str]) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._proxies: list[str] = list(proxies)
        self._index: int = 0
        self._failures: dict[str, int] = {}
        self._max_failures: int = int(MAGIC["proxy"]["max_failures"])
        self._profile_idx: int = random.randrange(len(_BROWSER_PROFILES))

    @classmethod
    def from_auto(cls) -> ProxyPool:
        print("Fetching and validating proxies...", flush=True)
        proxies: list[str] = fetch_live_proxies()
        if not proxies:
            print("WARNING: No live proxies found. Using direct connection.", flush=True)
        return cls(proxies)

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
