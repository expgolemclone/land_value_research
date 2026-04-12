from __future__ import annotations

import logging
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.browser import BrowserServiceError
from src.config import MAGIC
from src.utils import validate_url_not_private

if TYPE_CHECKING:
    from src.browser import BrowserService
    from src.stealth import ProxyPool

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MS = 30000
_KABUTAN_URL_TEMPLATE = "https://kabutan.jp/stock/?code={code}"
_KABUTAN_TIMEOUT_SEC = 20.0
_KABUTAN_MAX_RETRIES = 3
_KABUTAN_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
)
_KABUTAN_MARKET_CAP_PATTERN = re.compile(
    r"<th[^>]*>\s*時価総額\s*</th>\s*\n?\s*<td[^>]*>([\d,]+)<span>([^<]+)</span>",
)


@dataclass(frozen=True)
class CompanyMetadata:
    company_name: str = ""
    securities_report_pdf_url: str = ""
    market_cap_yen: int | None = None
    address_source_url: str = ""


_METADATA_CACHE: dict[str, CompanyMetadata] = {}
_METADATA_CACHE_LOCK: threading.Lock = threading.Lock()


def _fetch_text(
    url: str,
    *,
    browser: BrowserService,
    pool: ProxyPool | None = None,
) -> str:
    validate_url_not_private(url)
    proxy_url: str | None = pool.get() if pool is not None else None
    resp = browser.fetch(url, proxy=proxy_url, timeout=DEFAULT_TIMEOUT_MS)
    if resp.html is None:
        raise BrowserServiceError(f"browser fetch failed for {url}: status={resp.status} error={resp.error}")
    return resp.html


def _parse_yen_text(text: str) -> int | None:
    raw = (text or "").replace(",", "").strip()
    if not raw:
        return None
    # 例: 2兆1917億円, 247億9909万円, 5410百万円
    total = 0.0
    for unit, mult in [("兆", 10**12), ("億", 10**8), ("万", 10**4), ("百万円", 10**6)]:
        m = re.search(rf"([0-9]+(?:\.[0-9]+)?)\s*{re.escape(unit)}", raw)
        if m:
            total += float(m.group(1)) * mult
    if total > 0:
        return int(total)
    m_num = re.search(r"([0-9]+(?:\.[0-9]+)?)", raw)
    if m_num:
        return int(float(m_num.group(1)))
    return None


def fetch_market_cap_from_kabutan(
    code: str,
    pool: ProxyPool | None = None,
) -> int | None:
    """kabutanの個別株ページから時価総額(円)を取得する。Cloudflare不要のplain HTTPS。"""
    code = str(code).strip()
    if not code or not re.fullmatch(r"\d{3,4}[A-Z]?", code):
        return None
    url: str = _KABUTAN_URL_TEMPLATE.format(code=code)
    delay: float = float(MAGIC["scrape"]["delay_min"])

    for attempt in range(_KABUTAN_MAX_RETRIES):
        if attempt > 0:
            time.sleep(delay)
        req: urllib.request.Request = urllib.request.Request(
            url,
            headers={
                "User-Agent": _KABUTAN_USER_AGENT,
                "Accept-Language": "ja,en;q=0.9",
            },
        )
        proxy_addr: str | None = pool.get() if pool is not None and not pool.direct else None
        if proxy_addr is not None:
            req.set_proxy(proxy_addr, "https")
        try:
            with urllib.request.urlopen(req, timeout=_KABUTAN_TIMEOUT_SEC) as resp:
                raw: bytes = resp.read()
                encoding: str = resp.headers.get_content_charset() or "utf-8"
                html: str = raw.decode(encoding, errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                logger.info("kabutan: 銘柄ページなし: %s", code)
                return None
            logger.warning("kabutan: HTTP %d for %s (attempt %d)", exc.code, code, attempt + 1)
            continue
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning("kabutan: fetch error for %s (attempt %d): %s", code, attempt + 1, exc)
            continue

        m: re.Match[str] | None = _KABUTAN_MARKET_CAP_PATTERN.search(html)
        if m is None:
            logger.debug("kabutan: 時価総額パターン不一致: %s", code)
            return None
        value_str: str = m.group(1).replace(",", "") + m.group(2)
        result: int | None = _parse_yen_text(value_str)
        if result is not None:
            logger.info("kabutan: %s 時価総額=%s円", code, f"{result:,}")
        return result

    logger.warning("kabutan: %s 全リトライ失敗", code)
    return None


def fetch_from_irbank(
    code: str,
    *,
    browser: BrowserService,
    pool: ProxyPool | None = None,
) -> CompanyMetadata:
    code = str(code).strip()
    if not code or not re.fullmatch(r"\d{3,4}[A-Z]?", code):
        return CompanyMetadata()
    with _METADATA_CACHE_LOCK:
        cached = _METADATA_CACHE.get(code)
    if cached is not None:
        return cached

    ir_url: str = f"https://irbank.net/{code}/ir"
    edinet_url: str = f"https://irbank.net/{code}/edinet"

    company_name: str = ""
    market_cap_yen: int | None = None
    securities_report_pdf_url: str = ""
    ir_ok: bool = False
    edinet_ok: bool = False

    with ThreadPoolExecutor(max_workers=2) as executor:
        ir_future = executor.submit(_fetch_text, ir_url, browser=browser, pool=pool)
        edinet_future = executor.submit(_fetch_text, edinet_url, browser=browser, pool=pool)

        try:
            html_ir = ir_future.result()
            ir_ok = True
            m_name = re.search(r"<h1[^>]*>([^<（]+)（\d+[A-Z]?）のIR情報・決算資料</h1>", html_ir)
            if m_name:
                company_name = m_name.group(1).strip()
            m_cap = re.search(r"<dt>時価</dt><dd>([^<]+)</dd>", html_ir)
            if m_cap:
                market_cap_yen = _parse_yen_text(m_cap.group(1))
        except BrowserServiceError:
            logger.debug("IRBank IR page fetch failed: %s", ir_url, exc_info=True)

        try:
            html_edinet = edinet_future.result()
            edinet_ok = True
            # 有価証券報告書の最新 doc id を1件取得
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

    meta = CompanyMetadata(
        company_name=company_name,
        securities_report_pdf_url=securities_report_pdf_url,
        market_cap_yen=market_cap_yen,
        address_source_url=(ir_url if ir_ok else ""),
    )
    # 通信断などの一時失敗を固定化しないため、空結果はキャッシュしない。
    has_data = meta.company_name or meta.securities_report_pdf_url or (meta.market_cap_yen is not None)
    if has_data or (ir_ok and edinet_ok):
        with _METADATA_CACHE_LOCK:
            _METADATA_CACHE[code] = meta
    return meta
