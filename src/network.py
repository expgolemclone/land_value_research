from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request

DEFAULT_RETRY_COUNT = 3
DEFAULT_BACKOFF_SEC = 1.0

_TRANSIENT_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}


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


def urlopen_with_retry(
    req: urllib.request.Request,
    *,
    timeout_sec: float,
    retries: int = DEFAULT_RETRY_COUNT,
    backoff_sec: float = DEFAULT_BACKOFF_SEC,
) -> bytes:
    attempts = max(1, int(retries))
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                return resp.read()
        except Exception as e:
            if attempt >= attempts or (not is_transient_network_error(e)):
                raise
            time.sleep(float(backoff_sec) * (2 ** (attempt - 1)))
    raise RuntimeError("unreachable")
