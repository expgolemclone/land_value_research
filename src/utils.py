import contextlib
import ipaddress
import logging
import os
import urllib.parse
from collections.abc import Generator
from io import TextIOWrapper

logger = logging.getLogger(__name__)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


_CSV_ENCODINGS: list[str] = ["utf-8-sig", "cp932"]


@contextlib.contextmanager
def open_csv(path: str | os.PathLike[str]) -> Generator[TextIOWrapper, None, None]:
    """CSVファイルを utf-8-sig → cp932 の順で開く."""
    last_error: UnicodeDecodeError | None = None
    for enc in _CSV_ENCODINGS:
        try:
            f = open(path, encoding=enc, newline="")
            yield f
            f.close()
            return
        except UnicodeDecodeError as e:
            last_error = e
    if last_error is not None:
        raise last_error
    raise RuntimeError("unreachable")


def validate_url_not_private(url: str) -> None:
    """Raise ValueError if *url* points to a private / loopback address (SSRF guard)."""
    parsed = urllib.parse.urlparse(url)
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError(f"URLにホスト名がありません: {url}")
    if hostname in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        raise ValueError(f"ローカルホストへのアクセスはブロックされています: {url}")
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        logger.debug("Not an IP, allowing hostname: %s", hostname)
        return
    if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
        raise ValueError(f"プライベート/予約済みIPへのアクセスはブロックされています: {url}")
