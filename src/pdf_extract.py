from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import pdfplumber

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FacilityLand:
    site_name: str
    location_short: str
    land_area_m2: float
    land_book_value_yen: float


_FW_TRANSLATE = str.maketrans("０１２３４５６７８９，．（）－", "0123456789,.()-")
_RE_PAGENO = re.compile(r"^\d+/\d+$")
_RE_LAND_AREA = re.compile(r"(?P<land>\d[\d,]*(?:\.\d+)?)\s*[（(]\s*(?P<area>\d[\d,]*(?:\.\d+)?)\s*[）)]")
_RE_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_RE_LOCATION = re.compile(
    r"(東京都|北海道|京都府|大阪府|[^\s()（）]{1,8}県)"
    r"[^()（）]{0,40}?"
    r"(区|市|町|村|郡[^\s()（）]{0,20}(町|村))"
)


def _normalize_text(s: str) -> str:
    return (s or "").translate(_FW_TRANSLATE).strip()


def _parse_number(cell: str) -> float | None:
    s = _normalize_text(cell)
    if not s or s in {"-", "－", "ー", "―", "─"}:
        return None
    m = _RE_NUMBER.search(s)
    if not m:
        return None
    return float(m.group(0).replace(",", ""))


def _parse_land_cell(cell: str) -> tuple[float | None, float | None]:
    s = _normalize_text(cell or "")
    if not s:
        return None, None

    # [] や () は注記が多いため, 主値は注記外の最初の数値を採用する.
    flat = s.replace("\n", " ")
    flat = re.sub(r"\[[^\]]*\]", " ", flat)
    flat = re.sub(r"[（(][^）)]*[）)]", " ", flat)
    land_val = _parse_number(flat)

    area_val: float | None = None
    m_area = re.search(r"[（(]\s*(\d[\d,]*(?:\.\d+)?)\s*[）)]", s)
    if m_area:
        area_val = float(m_area.group(1).replace(",", ""))

    return land_val, area_val


def _parse_land_area_cell(cell: str) -> float | None:
    s = _normalize_text(cell or "")
    if not s:
        return None
    # 土地面積列は [] が内書き, () が外書きなので, 主値は注記外を優先する.
    flat = s.replace("\n", " ")
    flat = re.sub(r"\[[^\]]*\]", " ", flat)
    flat = re.sub(r"[（(][^）)]*[）)]", " ", flat)
    return _parse_number(flat)


def _extract_location(site_cell: str) -> str:
    flat = re.sub(r"\s+", "", _normalize_text(site_cell))
    m = _RE_LOCATION.search(flat)
    if not m:
        return ""
    loc = m.group(0)
    loc = re.sub(r"他$", "", loc)
    loc = re.sub(r"ほか.*$", "", loc)
    return loc


def _extract_site_name(site_cell: str) -> str:
    raw = _normalize_text(site_cell)
    lines = [x.strip() for x in raw.splitlines() if x.strip()]
    first = lines[0] if lines else ""
    first = first.split("(", 1)[0].split("（", 1)[0].strip()
    if len(lines) >= 2:
        second = lines[1].split("(", 1)[0].split("（", 1)[0].strip()
        if second and not re.search(r"(都|道|府|県|区|市|町|村)", second) and not _RE_NUMBER.search(second):
            first = f"{first}{second}"
    if first.endswith("及び") and len(lines) >= 2:
        second = lines[1].split("(", 1)[0].split("（", 1)[0].strip()
        if second:
            first = f"{first}{second}"
    return first or "不明"


def _book_multiplier(header_text: str) -> int:
    if "帳簿価額(千円)" in header_text or "帳簿価額（千円）" in header_text:
        return 1_000
    if "帳簿価額(百万円)" in header_text or "帳簿価額（百万円）" in header_text:
        return 1_000_000
    return 1_000_000


def _area_scale(header_text: str) -> float:
    if "面積千㎡" in header_text or "(千㎡)" in header_text or "（千㎡）" in header_text:
        return 1_000.0
    return 1.0


def _join_header_columns(table: list[list[str | None]], header_row_count: int) -> list[str]:
    width = max((len(r) for r in table), default=0)
    headers = [""] * width
    for i in range(header_row_count):
        row = table[i]
        for c in range(width):
            val = _normalize_text(row[c]) if c < len(row) and row[c] else ""
            if val:
                headers[c] = f"{headers[c]} {val}".strip()
    headers = [h.replace("\n", "").replace(" ", "") for h in headers]
    return headers


def _find_data_start(table: list[list[str | None]]) -> int:
    for i, row in enumerate(table):
        c0 = _normalize_text(row[0]) if row and row[0] else ""
        if not c0:
            continue
        if "事業所名" in c0 or "所在地" in c0 or "会社名" in c0:
            continue
        if re.search(r"(都|道|府|県)", c0):
            return i
    return -1


def _extract_from_table(
    table: list[list[str | None]],
    skip_hq_row: bool = False,
) -> tuple[list[FacilityLand], list[str]]:
    data_start = _find_data_start(table)
    if data_start <= 0:
        return [], []

    headers = _join_header_columns(table, data_start)
    header_text = "".join(headers)
    if "事業所名" not in header_text:
        return [], []

    book_mult = _book_multiplier(header_text)
    area_scale = _area_scale(header_text)

    land_col = None
    area_col = None
    land_area_col = None
    for i, h in enumerate(headers):
        if land_col is None and ("土地" in h) and ("土地面積" not in h):
            land_col = i
        if land_area_col is None and ("土地面積" in h):
            land_area_col = i
        if area_col is None and ("面積" in h):
            area_col = i

    out: list[FacilityLand] = []
    missing_area_errors: list[str] = []
    for row in table[data_start:]:
        if not row:
            continue
        site_cell = row[0] if len(row) > 0 and row[0] else ""
        site_name = _extract_site_name(site_cell)
        if not site_name or site_name.startswith("計"):
            continue
        if skip_hq_row and site_name == "本社":
            continue

        location = _extract_location(site_cell)
        if not location:
            continue

        land = None
        area = None

        if land_col is not None and land_col < len(row):
            land, area = _parse_land_cell(row[land_col] or "")

        if (land is None or area is None) and land_col is None:
            for cell in row:
                cell_norm = _normalize_text(cell or "").replace("\n", "")
                m = _RE_LAND_AREA.search(cell_norm)
                if m:
                    land = float(m.group("land").replace(",", ""))
                    area = float(m.group("area").replace(",", ""))
                    break

        if land_col is not None and land is None:
            continue

        if area is None and land_area_col is not None and land_area_col < len(row):
            area = _parse_land_area_cell(row[land_area_col] or "")

        if area is None and land_col is not None and land_col + 1 < len(row):
            next_header = headers[land_col + 1] if land_col + 1 < len(headers) else ""
            if "面積" in (next_header or ""):
                area = _parse_number(row[land_col + 1] or "")

        if area is None and land_col is None and area_col is not None and area_col < len(row):
            area = _parse_number(row[area_col] or "")

        # 土地と面積が隣接列に分かれる表(例: 9083)への対応
        if (
            land is not None
            and area is not None
            and land > 0
            and area > 0
            and abs(area - land) < 1e-6
            and land_col is not None
            and land_col + 1 < len(row)
        ):
            side = _parse_number(row[land_col + 1] or "")
            if side is not None and side > area:
                area = side

        if land is None and land_col is None and area_col is not None:
            for c in [area_col + 1, area_col - 1]:
                if c < 0 or c >= len(row):
                    continue
                v = _parse_number(row[c] or "")
                if v is not None:
                    land = v
                    break

        if land is None or area is None:
            if land is not None and area is None and location.startswith("東京都"):
                missing_area_errors.append(f"事業所名={site_name}, 所在地={location}, 土地簿価(raw)={land}")
            continue

        out.append(
            FacilityLand(
                site_name=site_name,
                location_short=location,
                land_area_m2=area * area_scale,
                land_book_value_yen=land * book_mult,
            )
        )

    return out, missing_area_errors


def extract_major_facilities_land(pdf_path: str) -> list[FacilityLand]:
    out: list[FacilityLand] = []
    missing_area_errors: list[str] = []
    in_section = False
    skip_hq_row = False

    try:
        pdf_file = pdfplumber.open(pdf_path)
    except Exception as e:
        logger.warning("PDF解析失敗(破損の可能性): %s: %s: %s", pdf_path, type(e).__name__, e)
        return []

    with pdf_file as pdf:
        for page in pdf.pages:
            txt = _normalize_text(page.extract_text() or "")
            if not txt:
                continue
            if (not in_section) and ("主要な設備の状況" in txt) and ("帳簿価額" in txt):
                in_section = True
            if not in_section:
                continue
            txt_compact = re.sub(r"\s+", "", txt)
            if ("本社欄に記載の土地" in txt_compact) and ("各所に所在" in txt_compact):
                skip_hq_row = True
            for table in page.extract_tables() or []:
                rows, errs = _extract_from_table(table, skip_hq_row=skip_hq_row)
                out.extend(rows)
                missing_area_errors.extend(errs)
            if re.search(r"[３3]\s*【\s*設備の新設", txt):
                break

    if missing_area_errors:
        detail = " / ".join(missing_area_errors[:5])
        if len(missing_area_errors) > 5:
            detail += f" / ...({len(missing_area_errors)}件)"
        print(f"Warn(missing land area): {pdf_path} {detail}")

    dedup: dict[tuple[str, str], FacilityLand] = {}
    for x in out:
        dedup[(x.site_name, x.location_short)] = x
    values = list(dedup.values())
    if skip_hq_row:
        values = [x for x in values if x.site_name != "本社"]
    return values
