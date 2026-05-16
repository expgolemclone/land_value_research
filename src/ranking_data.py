from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import TypedDict

from src.company_store import CompanyDirectory
from src.config import DEFAULT_OUTPUT_DIR, PROJECT_ROOT
from src.schema import (
    COL_ANOMALY_WARNING,
    COL_BOOK_VALUE,
    COL_CODE,
    COL_COMPANY_NAME,
    COL_CONFIDENCE,
    COL_ESTIMATED_VALUE,
    COL_GEOCODE_LEVEL,
    COL_MARKET_CAP,
    COL_RATIO,
    COL_RATIO_RAW,
    COL_SITE_NAME,
    COL_UNREALIZED_GAIN,
)
from src.utils import open_csv

logger = logging.getLogger(__name__)

DEFAULT_INPUT_DIR = DEFAULT_OUTPUT_DIR
DOCS_DIR = PROJECT_ROOT / "split-address"


class RankingRow(TypedDict):
    code: str
    name: str
    pdf_url: str
    ratio: float
    estimated_value: str
    market_cap: str
    book_value: str
    unrealized_gain: str
    geocode_tag: str
    memo_markdown: str
    tag_count: int
    confidence: str
    anomaly: str
    source_file: str


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with open_csv(path) as f:
        return list(csv.DictReader(f))


def to_float(raw: str | float | int | None) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, int | float):
        return float(raw)
    s = raw.strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        logger.debug("float conversion failed: %r", s)
        return None


def normalize_company_name(code: str, raw_name: str, company_records: CompanyDirectory) -> str:
    name = (raw_name or "").strip()
    normalized_code = (code or "").strip()
    if not normalized_code:
        return name

    if not name:
        return company_records.get(normalized_code, {}).get("company_name", "")

    compact_name = name.replace(" ", "")
    if compact_name == normalized_code:
        return company_records.get(normalized_code, {}).get("company_name", name)

    return name


def pick_company_row(rows: list[dict[str, str]]) -> dict[str, str] | None:
    if not rows:
        return None

    total_rows = [r for r in rows if (r.get(COL_SITE_NAME) or "").strip() == "東京都合計"]
    candidates = total_rows if total_rows else rows

    best_row: dict[str, str] | None = None
    best_ratio = float("-inf")
    for row in candidates:
        ratio = to_float(row.get(COL_RATIO_RAW, ""))
        if ratio is None:
            ratio = to_float(row.get(COL_RATIO, ""))
        if ratio is None:
            continue
        if ratio > best_ratio:
            best_ratio = ratio
            best_row = row
    return best_row


def collect_unique_values(rows: list[dict[str, str]], key: str) -> str:
    values: list[str] = []
    seen: set[str] = set()
    for row in rows:
        value = " ".join((row.get(key) or "").strip().replace("|", " / ").split())
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return " / ".join(values)


def count_unique_values(rows: list[dict[str, str]], key: str) -> int:
    seen: set[str] = set()
    for row in rows:
        value = (row.get(key) or "").strip()
        if not value:
            continue
        seen.add(value)
    return len(seen)


def markdown_to_html(text: str) -> str:
    """Markdownテキストを簡易HTMLに変換する（外部ライブラリ不要）."""
    import html
    import re

    lines = text.replace("\r", "").split("\n")
    out: list[str] = []
    in_ul = False
    in_table = False
    table_has_header = False

    def _inline(s: str) -> str:
        s = html.escape(s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" target="_blank">\1</a>', s)

    def _close_list() -> None:
        nonlocal in_ul
        if in_ul:
            out.append("</ul>")
            in_ul = False

    def _close_table() -> None:
        nonlocal in_table, table_has_header
        if in_table:
            out.append("</tbody></table>")
            in_table = False
            table_has_header = False

    for line in lines:
        stripped = line.strip()

        if not stripped:
            _close_list()
            _close_table()
            continue

        m = re.match(r"^(#{1,4})\s+(.*)", stripped)
        if m:
            _close_list()
            _close_table()
            level = min(len(m.group(1)) + 2, 6)
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            continue

        if re.match(r"^\|[\s\-:|]+\|$", stripped):
            table_has_header = True
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not in_table:
                _close_list()
                in_table = True
                table_has_header = False
                out.append('<table class="md-table"><thead><tr>')
                out.append("".join(f"<th>{_inline(c)}</th>" for c in cells))
                out.append("</tr></thead><tbody>")
                continue
            out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
            continue

        m = re.match(r"^[-*]\s+(.*)", stripped)
        if m:
            _close_table()
            if not in_ul:
                in_ul = True
                out.append("<ul>")
            out.append(f"<li>{_inline(m.group(1))}</li>")
            continue

        _close_list()
        _close_table()
        out.append(f"<p>{_inline(stripped)}</p>")

    _close_list()
    _close_table()
    return "\n".join(out)


def collect_rank_rows(
    input_dir: Path | None = None,
    company_records: CompanyDirectory | None = None,
) -> list[RankingRow]:
    resolved_input_dir = input_dir or DEFAULT_INPUT_DIR
    resolved_company_records = company_records or {}

    rank_rows: list[RankingRow] = []
    for csv_path in sorted(resolved_input_dir.glob("*_output.csv")):
        rows = read_csv_rows(csv_path)
        company_row = pick_company_row(rows)
        if company_row is None:
            continue

        ratio = to_float(company_row.get(COL_RATIO_RAW, ""))
        if ratio is None:
            ratio = to_float(company_row.get(COL_RATIO, ""))
        if ratio is None:
            continue

        code = (company_row.get(COL_CODE) or "").strip()
        company_name = normalize_company_name(code, company_row.get(COL_COMPANY_NAME, ""), resolved_company_records)

        docs_path = DOCS_DIR / f"{code}.md"
        docs_content = ""
        if docs_path.exists():
            try:
                docs_content = docs_path.read_text(encoding="utf-8")
            except OSError:
                logger.debug("Failed to read docs file: %s", docs_path)

        rank_rows.append(
            {
                "code": code,
                "name": company_name,
                "pdf_url": resolved_company_records.get(code, {}).get("securities_report_pdf_url", "").strip(),
                "ratio": ratio,
                "estimated_value": (company_row.get(COL_ESTIMATED_VALUE) or "").strip(),
                "market_cap": (company_row.get(COL_MARKET_CAP) or "").strip(),
                "book_value": (company_row.get(COL_BOOK_VALUE) or "").strip(),
                "unrealized_gain": (company_row.get(COL_UNREALIZED_GAIN) or "").strip(),
                "geocode_tag": collect_unique_values(rows, COL_GEOCODE_LEVEL),
                "memo_markdown": docs_content,
                "tag_count": count_unique_values(rows, COL_GEOCODE_LEVEL),
                "confidence": collect_unique_values(rows, COL_CONFIDENCE),
                "anomaly": collect_unique_values(rows, COL_ANOMALY_WARNING),
                "source_file": csv_path.name,
            }
        )

    rank_rows.sort(key=lambda r: r["ratio"], reverse=True)
    return rank_rows
