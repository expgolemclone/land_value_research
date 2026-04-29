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
    securities_report_pdf_url: str = ""


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
    need_pdf: bool = True,
) -> CompanyMetadata:
    code = str(code).strip()
    if not code or not re.fullmatch(r"\d{3,4}[A-Z]?", code):
        return CompanyMetadata()
    with _METADATA_CACHE_LOCK:
        cached = _METADATA_CACHE.get(code)
    if cached is not None and (not need_name or cached.company_name) and (not need_pdf or cached.securities_report_pdf_url):
        return cached

    ir_url: str = f"https://irbank.net/{code}/ir"
    edinet_url: str = f"https://irbank.net/{code}/edinet"

    company_name: str = cached.company_name if cached is not None else ""
    securities_report_pdf_url: str = cached.securities_report_pdf_url if cached is not None else ""
    request_ir = need_name and not company_name
    request_edinet = need_pdf and not securities_report_pdf_url
    ir_ok = not request_ir
    edinet_ok = not request_edinet
    futures: dict[str, object] = {}

    if request_ir or request_edinet:
        with ThreadPoolExecutor(max_workers=int(request_ir) + int(request_edinet)) as executor:
            if request_ir:
                futures["ir"] = executor.submit(_fetch_text, ir_url, browser=browser)
            if request_edinet:
                futures["edinet"] = executor.submit(_fetch_text, edinet_url, browser=browser)

            if request_ir:
                try:
                    html_ir = futures["ir"].result()
                    ir_ok = True
                    m_name = re.search(r"<h1[^>]*>([^<（]+)（\d+[A-Z]?）のIR情報・決算資料</h1>", html_ir)
                    if m_name:
                        company_name = m_name.group(1).strip()
                except BrowserServiceError:
                    logger.debug("IRBank IR page fetch failed: %s", ir_url, exc_info=True)

            if request_edinet:
                try:
                    html_edinet = futures["edinet"].result()
                    edinet_ok = True
                    doc_ids = re.findall(
                        r'title="有価証券報告書[^"]*" href="notes\?f=(S100[0-9A-Z]+)"',
                        html_edinet,
                    )
                    if not doc_ids:
                        doc_ids = re.findall(
                            r'href="notes\?f=(S100[0-9A-Z]+)" title="有価証券報告書[^"]*"',
                            html_edinet,
                        )
                    if doc_ids:
                        securities_report_pdf_url = (
                            f"https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/{doc_ids[0]}.pdf"
                        )
                except BrowserServiceError:
                    logger.debug("IRBank EDINET page fetch failed: %s", edinet_url, exc_info=True)

    meta = CompanyMetadata(company_name=company_name, securities_report_pdf_url=securities_report_pdf_url)
    # 通信断などの一時失敗を固定化しないため、空結果はキャッシュしない。
    has_data = meta.company_name or meta.securities_report_pdf_url
    if has_data or (ir_ok and edinet_ok):
        with _METADATA_CACHE_LOCK:
            _METADATA_CACHE[code] = meta
    return meta
