from __future__ import annotations

import os
from typing import TYPE_CHECKING

from src.utils import validate_url_not_private

if TYPE_CHECKING:
    from src.browser import BrowserService
    from src.stealth import ProxyPool

DEFAULT_TIMEOUT_MS = 60000


def is_pdf_file(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head: bytes = f.read(5)
        return head == b"%PDF-"
    except OSError:
        return False


def download_file(
    url: str,
    out_path: str,
    *,
    browser: BrowserService,
    pool: ProxyPool | None = None,
) -> None:
    validate_url_not_private(url)
    out_dir: str = os.path.dirname(out_path)
    os.makedirs(out_dir, exist_ok=True)

    proxy_url: str | None = pool.get() if pool is not None else None
    downloaded_path: str = browser.download(
        url,
        download_dir=out_dir,
        proxy=proxy_url,
        timeout=DEFAULT_TIMEOUT_MS,
    )
    if not is_pdf_file(downloaded_path):
        try:
            os.remove(downloaded_path)
        except OSError:
            pass
        raise ValueError(f"PDF取得に失敗しました. URLがPDF直リンクではない可能性があります: {url}")

    if downloaded_path != out_path:
        os.replace(downloaded_path, out_path)
