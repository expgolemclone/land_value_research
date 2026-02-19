import logging
import re
import urllib.request
from dataclasses import dataclass
from functools import lru_cache

from src.utils import validate_url_not_private

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SEC = 20


@dataclass(frozen=True)
class CompanyMetadata:
    company_name: str = ""
    securities_report_pdf_url: str = ""
    market_cap_yen: int | None = None
    address_source_url: str = ""


def _fetch_text(url: str) -> str:
    validate_url_not_private(url)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; land_value_research/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_SEC) as resp:
        return resp.read().decode("utf-8", errors="ignore")


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


@lru_cache(maxsize=4096)
def fetch_from_irbank(code: str) -> CompanyMetadata:
    code = str(code).strip()
    if not code or not re.fullmatch(r"\d{4}", code):
        return CompanyMetadata()

    ir_url = f"https://irbank.net/{code}/ir"
    edinet_url = f"https://irbank.net/{code}/edinet"

    company_name = ""
    market_cap_yen: int | None = None
    securities_report_pdf_url = ""

    try:
        html_ir = _fetch_text(ir_url)
        m_name = re.search(r"<h1><a[^>]*>\d+\s+([^<]+)</a></h1>", html_ir)
        if m_name:
            company_name = m_name.group(1).strip()
        m_cap = re.search(r"<dt>時価</dt><dd>([^<]+)</dd>", html_ir)
        if m_cap:
            market_cap_yen = _parse_yen_text(m_cap.group(1))
    except Exception:
        logger.debug("IRBank IR page fetch failed: %s", ir_url, exc_info=True)

    try:
        html_edinet = _fetch_text(edinet_url)
        # 有価証券報告書の最新 doc id を1件取得
        doc_ids = re.findall(
            r'title="有価証券報告書[^"]*" href="notes\?f=(S100[0-9A-Z]+)"',
            html_edinet,
        )
        if doc_ids:
            securities_report_pdf_url = f"https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/{doc_ids[0]}.pdf"
    except Exception:
        logger.debug("IRBank EDINET page fetch failed: %s", edinet_url, exc_info=True)

    return CompanyMetadata(
        company_name=company_name,
        securities_report_pdf_url=securities_report_pdf_url,
        market_cap_yen=market_cap_yen,
        address_source_url=ir_url,
    )
