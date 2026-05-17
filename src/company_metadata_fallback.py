from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.browser import BrowserServiceError
from src.utils import validate_url_not_private

if TYPE_CHECKING:
    from src.browser import BrowserService

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MS = 30000


@dataclass(frozen=True)
class CompanyMetadata:
    company_name: str = ""


_METADATA_CACHE: dict[str, CompanyMetadata] = {}
_METADATA_CACHE_LOCK: threading.Lock = threading.Lock()


def _fetch_text(
    url: str,
    *,
    browser: BrowserService,
) -> str:
    validate_url_not_private(url)
    resp = browser.fetch(url, timeout=DEFAULT_TIMEOUT_MS)
    if resp.html is None:
        raise BrowserServiceError(f"browser fetch failed for {url}: status={resp.status} error={resp.error}")
    return resp.html


def fetch_from_irbank(
    code: str,
    *,
    browser: BrowserService,
    need_name: bool = True,
) -> CompanyMetadata:
    code = str(code).strip()
    if not code or not re.fullmatch(r"\d{3,4}[A-Z]?", code):
        return CompanyMetadata()
    with _METADATA_CACHE_LOCK:
        cached = _METADATA_CACHE.get(code)
    if cached is not None and (not need_name or cached.company_name):
        return cached

    ir_url: str = f"https://irbank.net/{code}/ir"

    company_name: str = cached.company_name if cached is not None else ""
    request_ir = need_name and not company_name
    ir_ok = not request_ir
    futures: dict[str, object] = {}

    if request_ir:
        with ThreadPoolExecutor(max_workers=1) as executor:
            if request_ir:
                futures["ir"] = executor.submit(_fetch_text, ir_url, browser=browser)

            if request_ir:
                try:
                    html_ir = futures["ir"].result()
                    ir_ok = True
                    m_name = re.search(r"<h1[^>]*>([^<（]+)（\d+[A-Z]?）のIR情報・決算資料</h1>", html_ir)
                    if m_name:
                        company_name = m_name.group(1).strip()
                except BrowserServiceError:
                    logger.debug("IRBank IR page fetch failed: %s", ir_url, exc_info=True)

    meta = CompanyMetadata(company_name=company_name)
    # 通信断などの一時失敗を固定化しないため、空結果はキャッシュしない。
    has_data = bool(meta.company_name)
    if has_data or ir_ok:
        with _METADATA_CACHE_LOCK:
            _METADATA_CACHE[code] = meta
    return meta
