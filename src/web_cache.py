from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from src.utils import validate_url_not_private

if TYPE_CHECKING:
    from src.browser import BrowserService

DEFAULT_TIMEOUT_MS = 60000


def is_pdf_file(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head: bytes = f.read(5)
        return head == b"%PDF-"
    except OSError:
        logger.debug("Failed to check PDF header: %s", path)
        return False


def download_file(
    url: str,
    out_path: str,
    *,
    browser: BrowserService,
) -> None:
    validate_url_not_private(url)
    out_dir: str = os.path.dirname(out_path)
    os.makedirs(out_dir, exist_ok=True)

    downloaded_path: str = browser.download(
        url,
        download_dir=out_dir,
        timeout=DEFAULT_TIMEOUT_MS,
    )
    if not is_pdf_file(downloaded_path):
        try:
            os.remove(downloaded_path)
        except OSError:
            logger.debug("Failed to remove invalid download: %s", downloaded_path)
        raise ValueError(f"PDF取得に失敗しました. URLがPDF直リンクではない可能性があります: {url}")

    if downloaded_path != out_path:
        os.replace(downloaded_path, out_path)
