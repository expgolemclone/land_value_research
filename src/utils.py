import ipaddress
import os
import urllib.parse


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


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
        return  # normal hostname – allow
    if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
        raise ValueError(f"プライベート/予約済みIPへのアクセスはブロックされています: {url}")
