from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.stealth import ProxyPool

DEFAULT_RETRY_COUNT = 3
DEFAULT_BACKOFF_SEC = 1.0

_TRANSIENT_HTTP_STATUS: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})


def is_transient_network_error(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return int(exc.code) in _TRANSIENT_HTTP_STATUS
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, TimeoutError):
            return True
        if isinstance(reason, socket.timeout):
            return True
        if isinstance(reason, OSError):
            return True
        return False
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, socket.timeout):
        return True
    if isinstance(exc, ConnectionError):
        return True
    if isinstance(exc, OSError):
        return True
    return False


def _fetch_via_proxy(
    url: str,
    *,
    headers: dict[str, str],
    timeout_sec: float,
    pool: ProxyPool,
    retries: int,
    backoff_sec: float,
) -> bytes:
    from src.stealth import create_session

    attempts: int = max(1, retries)
    for attempt in range(1, attempts + 1):
        try:
            session = create_session(pool)
            resp = session.get(url, headers=headers, timeout=timeout_sec)
            if resp.status_code == 429:
                pool.report_failure()
                if attempt < attempts:
                    time.sleep(float(backoff_sec) * (2 ** (attempt - 1)))
                    continue
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            if attempt >= attempts or not is_transient_network_error(e):
                raise
            pool.report_failure()
            time.sleep(float(backoff_sec) * (2 ** (attempt - 1)))
    raise RuntimeError("unreachable")


def urlopen_with_retry(
    req: urllib.request.Request,
    *,
    timeout_sec: float,
    retries: int = DEFAULT_RETRY_COUNT,
    backoff_sec: float = DEFAULT_BACKOFF_SEC,
    pool: ProxyPool | None = None,
) -> bytes:
    if pool is not None:
        url: str = req.full_url
        headers: dict[str, str] = dict(req.header_items())
        return _fetch_via_proxy(
            url,
            headers=headers,
            timeout_sec=timeout_sec,
            pool=pool,
            retries=retries,
            backoff_sec=backoff_sec,
        )

    attempts: int = max(1, int(retries))
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                return resp.read()
        except Exception as e:
            if attempt >= attempts or (not is_transient_network_error(e)):
                raise
            time.sleep(float(backoff_sec) * (2 ** (attempt - 1)))
    raise RuntimeError("unreachable")
