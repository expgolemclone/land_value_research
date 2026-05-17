from __future__ import annotations

import html
import logging
import re
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from src.pdf_extract import (
    FacilityLand,
    _estimate_header_rows,
    _extract_from_table,
    _normalize_text,
    _should_skip_hq_row,
)

logger = logging.getLogger(__name__)

_HTML_SUFFIXES = {".htm", ".html", ".xhtml"}
_BLOCK_TAGS = {"br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "p", "tr"}
_MAX_WORKERS_WIN = 61


@dataclass(frozen=True)
class XbrlFacilitiesExtraction:
    sites: list[FacilityLand]
    section_text: str


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _parse_span(raw: str | None) -> int:
    if not raw:
        return 1
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def _parse_xml(path: Path) -> ET.Element:
    try:
        return ET.parse(path).getroot()
    except ET.ParseError:
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
        text = text.replace("&nbsp;", "&#160;")
        return ET.fromstring(text)


def _candidate_ixbrl_files(xbrl_path: str) -> list[Path]:
    root = Path(xbrl_path)
    if root.is_file() and root.suffix.lower() in _HTML_SUFFIXES:
        return [root]
    if not root.is_dir():
        return []

    public_doc = root / "XBRL" / "PublicDoc"
    search_roots = [public_doc] if public_doc.is_dir() else [root]
    files: list[Path] = []
    for search_root in search_roots:
        files.extend(
            path
            for path in search_root.rglob("*")
            if path.is_file() and path.suffix.lower() in _HTML_SUFFIXES
        )
    return sorted(files, key=lambda path: path.name)


def _is_major_facilities_block(elem: ET.Element) -> bool:
    if _local_name(elem.tag) != "nonnumeric":
        return False
    name = str(elem.attrib.get("name", ""))
    return name == "MajorFacilitiesTextBlock" or name.endswith(":MajorFacilitiesTextBlock")


def _major_facilities_blocks(root: ET.Element) -> list[ET.Element]:
    return [elem for elem in root.iter() if _is_major_facilities_block(elem)]


def _element_text(elem: ET.Element) -> str:
    parts: list[str] = []

    def visit(node: ET.Element) -> None:
        if node.text:
            parts.append(node.text)
        for child in list(node):
            if _local_name(child.tag) == "br":
                parts.append("\n")
            visit(child)
            if _local_name(child.tag) in _BLOCK_TAGS:
                parts.append("\n")
            if child.tail:
                parts.append(child.tail)

    visit(elem)
    text = html.unescape("".join(parts)).replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _row_cells(row: ET.Element) -> list[ET.Element]:
    return [child for child in list(row) if _local_name(child.tag) in {"td", "th"}]


def _html_table_to_grid(table: ET.Element) -> list[list[str | None]]:
    rows: list[list[str | None]] = []
    future_spans: dict[int, int] = {}

    for tr in (elem for elem in table.iter() if _local_name(elem.tag) == "tr"):
        current_spans = future_spans
        future_spans = {}
        row: list[str | None] = []
        col = 0
        max_prev_col = max(current_spans, default=-1)

        def consume_spans() -> bool:
            nonlocal col
            consumed = False
            while current_spans.get(col, 0) > 0:
                row.append(None)
                remaining = current_spans[col] - 1
                if remaining > 0:
                    future_spans[col] = max(future_spans.get(col, 0), remaining)
                col += 1
                consumed = True
            return consumed

        consume_spans()
        for cell in _row_cells(tr):
            consume_spans()
            colspan = _parse_span(cell.attrib.get("colspan"))
            rowspan = _parse_span(cell.attrib.get("rowspan"))
            row.append(_element_text(cell))
            for offset in range(colspan):
                if offset > 0:
                    row.append(None)
                if rowspan > 1:
                    future_spans[col + offset] = max(future_spans.get(col + offset, 0), rowspan - 1)
            col += colspan

        while col <= max_prev_col:
            if not consume_spans():
                row.append("")
                col += 1

        if row:
            rows.append(row)

    return rows


def _is_blank_cell(cell: str | None) -> bool:
    return cell is None or not _normalize_text(cell)


def _merge_continuation_rows(table: list[list[str | None]]) -> list[list[str | None]]:
    if len(table) < 2:
        return table

    header_rows = _estimate_header_rows(table)
    out: list[list[str | None]] = [list(row) for row in table[:header_rows]]

    for row in table[header_rows:]:
        current = list(row)
        is_continuation = (
            bool(out)
            and len(current) >= 2
            and all(_is_blank_cell(cell) for cell in current[:2])
            and any(not _is_blank_cell(cell) for cell in current[2:])
        )
        if not is_continuation:
            out.append(current)
            continue

        prev = out[-1]
        width = max(len(prev), len(current))
        if len(prev) < width:
            prev.extend([None] * (width - len(prev)))
        if len(current) < width:
            current.extend([None] * (width - len(current)))

        for i, cell in enumerate(current):
            if _is_blank_cell(cell):
                continue
            if _is_blank_cell(prev[i]):
                prev[i] = cell
            else:
                prev[i] = f"{prev[i]}\n{cell}"

    return out


def _extract_from_major_facilities_block(block: ET.Element, xbrl_path: str) -> XbrlFacilitiesExtraction:
    section_text = _normalize_text(_element_text(block))
    skip_hq_row = _should_skip_hq_row(section_text)
    sites: list[FacilityLand] = []
    missing_area_errors: list[str] = []

    for table in (elem for elem in block.iter() if _local_name(elem.tag) == "table"):
        rows, errs = _extract_from_table(
            _merge_continuation_rows(_html_table_to_grid(table)),
            skip_hq_row=skip_hq_row,
        )
        sites.extend(rows)
        missing_area_errors.extend(errs)

    if missing_area_errors:
        detail = " / ".join(missing_area_errors[:5])
        if len(missing_area_errors) > 5:
            detail += f" / ...({len(missing_area_errors)}件)"
        print(f"Warn(missing land area): {xbrl_path} {detail}")

    dedup: dict[tuple[str, str], FacilityLand] = {}
    for site in sites:
        dedup[(site.site_name, site.location_short)] = site
    values = list(dedup.values())
    if skip_hq_row:
        values = [site for site in values if site.site_name != "本社"]
    return XbrlFacilitiesExtraction(sites=values, section_text=section_text)


def extract_facilities_from_xbrl(xbrl_path: str) -> XbrlFacilitiesExtraction:
    all_sites: list[FacilityLand] = []
    section_texts: list[str] = []

    for path in _candidate_ixbrl_files(xbrl_path):
        try:
            root = _parse_xml(path)
        except (ET.ParseError, OSError) as exc:
            logger.debug("XBRL HTML parse failed: %s: %s", path, exc, exc_info=True)
            continue

        for block in _major_facilities_blocks(root):
            extracted = _extract_from_major_facilities_block(block, xbrl_path)
            all_sites.extend(extracted.sites)
            if extracted.section_text:
                section_texts.append(extracted.section_text)

    dedup: dict[tuple[str, str], FacilityLand] = {}
    for site in all_sites:
        dedup[(site.site_name, site.location_short)] = site
    return XbrlFacilitiesExtraction(
        sites=list(dedup.values()),
        section_text="\n\n".join(section_texts),
    )


def extract_major_facilities_land_from_xbrl(xbrl_path: str) -> list[FacilityLand]:
    return extract_facilities_from_xbrl(xbrl_path).sites


def extract_facilities_section_text_from_xbrl(xbrl_path: str) -> str:
    return extract_facilities_from_xbrl(xbrl_path).section_text


def _extract_one(args: tuple[str, str]) -> tuple[str, XbrlFacilitiesExtraction]:
    code, xbrl_path = args
    try:
        return code, extract_facilities_from_xbrl(xbrl_path)
    except (ET.ParseError, OSError) as exc:
        logger.warning("XBRL並列抽出失敗: %s: %s: %s", xbrl_path, type(exc).__name__, exc)
        return code, XbrlFacilitiesExtraction(sites=[], section_text="")


def batch_extract_facilities_from_xbrl(
    xbrl_paths: dict[str, str],
    max_workers: int = 4,
) -> dict[str, XbrlFacilitiesExtraction]:
    if not xbrl_paths:
        return {}

    if sys.platform == "win32":
        max_workers = min(max_workers, _MAX_WORKERS_WIN)
    max_workers = max(1, min(max_workers, len(xbrl_paths)))

    if len(xbrl_paths) == 1:
        code, path = next(iter(xbrl_paths.items()))
        return {code: extract_facilities_from_xbrl(path)}

    results: dict[str, XbrlFacilitiesExtraction] = {}
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_code = {
            executor.submit(_extract_one, (code, path)): code
            for code, path in xbrl_paths.items()
        }
        for future in as_completed(future_to_code):
            code, extracted = future.result()
            results[code] = extracted

    return results
