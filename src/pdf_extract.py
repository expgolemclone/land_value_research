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
    location_has_hoka: bool = False


@dataclass(frozen=True)
class _ColumnMap:
    """テーブルのカラム役割マッピング."""

    name_col: int
    location_col: int | None  # Noneなら name_col の括弧内から抽出
    land_book_col: int | None
    land_area_col: int | None  # Noneなら land_book_col 内の括弧から取得
    book_mult: int
    area_scale: float


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
    flat = re.sub(r"[※*]\s*\d+", " ", flat)
    flat = re.sub(r"\[[^\]]*\]", " ", flat)
    flat = re.sub(r"[（(][^）)]*[）)]", " ", flat)
    land_val = _parse_number(flat)

    area_val: float | None = None
    m_area = re.search(r"[（(]\s*(\d[\d,]*(?:\.\d+)?)\s*[）)]", s)
    if m_area:
        area_val = float(m_area.group(1).replace(",", ""))

    # 括弧内の値が主値と同じ場合、面積ではなく注記(単位換算値等)と判断する
    if land_val is not None and area_val is not None and abs(area_val - land_val) < 1e-6:
        area_val = None

    return land_val, area_val


def _parse_land_area_cell(cell: str) -> float | None:
    s = _normalize_text(cell or "")
    if not s:
        return None
    # 土地面積列は [] が内書き, () が外書きなので, 主値は注記外を優先する.
    flat = s.replace("\n", " ")
    # 注記マーカー (※1, *1 等) を除去 — "※1※2 10,255" で "1" を誤認するのを防ぐ
    flat = re.sub(r"[※*]\s*\d+", " ", flat)
    flat = re.sub(r"\[[^\]]*\]", " ", flat)
    flat = re.sub(r"[（(][^）)]*[）)]", " ", flat)
    return _parse_number(flat)


def _extract_location(site_cell: str) -> tuple[str, bool]:
    flat = re.sub(r"\s+", "", _normalize_text(site_cell))
    m = _RE_LOCATION.search(flat)
    if not m:
        return "", False
    loc = m.group(0)
    rest = flat[m.end() :]
    # "(東京都千代田区)他60営業所等" のように閉じ括弧の直後に "他/等/外" が続くケースがある
    rest = rest.lstrip(")）】]］")
    has_hoka = bool(re.search(r"^[他等外]|ほか|及び|その他", rest))
    loc = re.sub(r"他$", "", loc)
    loc = re.sub(r"ほか.*$", "", loc)
    return loc, has_hoka


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
    # 帳簿価額のラベルと単位が離れている場合 (例: "帳簿価額(注)3" + "土地等(百万円)")
    if "(百万円)" in header_text or "（百万円）" in header_text:
        return 1_000_000
    if "(千円)" in header_text or "（千円）" in header_text:
        return 1_000
    return 1_000_000


def _area_scale(header_text: str) -> float:
    if (
        "面積千㎡" in header_text
        or "(千㎡)" in header_text
        or "（千㎡）" in header_text
        or "(千m2)" in header_text
        or "（千m2）" in header_text
    ):
        return 1_000.0
    return 1.0


# ---------------------------------------------------------------------------
# Header parsing & column detection
# ---------------------------------------------------------------------------

_SUB_HEADER_KEYWORDS = ("帳簿", "面積", "百万", "千円", "建物", "土地", "その他", "合計", "規模", "竣工")


def _estimate_header_rows(table: list[list[str | None]]) -> int:
    """テーブルのヘッダー行数を推定する."""
    if len(table) < 2:
        return len(table)
    row1 = table[1]
    if not row1:
        return 1
    none_or_empty = sum(1 for c in row1 if c is None or not _normalize_text(c))
    keyword_count = sum(
        1 for c in row1 if c and any(k in _normalize_text(c) for k in _SUB_HEADER_KEYWORDS)
    )
    if none_or_empty >= max(len(row1) // 3, 1) or keyword_count >= 2:
        return 2
    return 1


def _parse_group_headers(
    table: list[list[str | None]],
    header_row_count: int,
) -> list[tuple[str, str]]:
    """マルチ行ヘッダーを解析し、各列の (group, sub) ペアを返す.

    row[0] でNoneが続く場合、直前の値と同じグループとみなす（セル結合）。
    row[1..n] を結合して sub とする。
    """
    width = max((len(r) for r in table[: header_row_count + 3]), default=0)

    # Group from row[0] with None-span detection
    groups: list[str] = []
    current = ""
    row0 = table[0] if table else []
    for c in range(width):
        val = _normalize_text(row0[c]) if c < len(row0) and row0[c] else ""
        if val:
            current = val
        groups.append(current)

    # Sub from remaining header rows
    subs: list[str] = [""] * width
    for i in range(1, header_row_count):
        if i >= len(table):
            break
        row = table[i]
        for c in range(width):
            val = _normalize_text(row[c]) if c < len(row) and row[c] else ""
            if val:
                subs[c] = f"{subs[c]}{val}" if subs[c] else val

    groups = [re.sub(r"\s+", "", g) for g in groups]
    subs = [re.sub(r"\s+", "", s) for s in subs]

    return list(zip(groups, subs))


def _detect_columns(
    group_headers: list[tuple[str, str]],
) -> _ColumnMap | None:
    """ヘッダーからカラム役割を動的に検出する.

    Returns None if the table is not a facilities land table.
    """
    name_col: int | None = None
    location_col: int | None = None
    land_area_col: int | None = None
    land_book_col: int | None = None

    # --- name_col / location_col ---
    for i, (g, _s) in enumerate(group_headers):
        if name_col is None:
            if "事業所名" in g:
                name_col = i
            elif "名称" in g and "会社名" not in g:
                name_col = i
        if location_col is None and g == "所在地":
            location_col = i

    if name_col is None:
        return None

    # --- land_area_col ---
    for i, (g, s) in enumerate(group_headers):
        if "土地面積" in g or "土地等面積" in g:
            land_area_col = i
            break
        # group="土地" + sub に "面積" あり、かつ金額単位なし → 面積専用列
        if "土地" in g and "面積" in s and "百万" not in s and "千円" not in s and "帳簿" not in s:
            land_area_col = i
            break

    # --- land_book_col ---
    for i, (g, s) in enumerate(group_headers):
        if i == land_area_col:
            continue
        # "帳簿価額" group + "土地" sub (3289/8801/8804 形式)
        if "帳簿価額" in g and "土地" in s and "面積" not in s:
            land_book_col = i
            break
        # "土地" group + "帳簿価額" sub (8802 形式)
        if "土地" in g and "面積" not in g and "帳簿価額" in s:
            land_book_col = i
            break

    # Fallback: combined "土地" column (standard format — 簿価と面積が1セル)
    if land_book_col is None:
        for i, (g, _s) in enumerate(group_headers):
            if i == land_area_col:
                continue
            if "土地" in g and "面積" not in g:
                land_book_col = i
                break

    if land_book_col is None:
        return None

    all_text = "".join(g + s for g, s in group_headers)

    return _ColumnMap(
        name_col=name_col,
        location_col=location_col,
        land_book_col=land_book_col,
        land_area_col=land_area_col,
        book_mult=_book_multiplier(all_text),
        area_scale=_area_scale(all_text),
    )


# ---------------------------------------------------------------------------
# Table extraction
# ---------------------------------------------------------------------------

_RE_SECTION_HEADER = re.compile(r"^[①-⑩]")


def _extract_from_table(
    table: list[list[str | None]],
    skip_hq_row: bool = False,
) -> tuple[list[FacilityLand], list[str]]:
    if not table or len(table) < 2:
        return [], []

    header_rows = _estimate_header_rows(table)
    group_headers = _parse_group_headers(table, header_rows)
    colmap = _detect_columns(group_headers)

    if colmap is None:
        return [], []

    out: list[FacilityLand] = []
    missing_area_errors: list[str] = []

    for row in table[header_rows:]:
        if not row:
            continue

        # --- Site name ---
        name_cell = row[colmap.name_col] if colmap.name_col < len(row) and row[colmap.name_col] else ""
        if not name_cell:
            continue
        norm_name = _normalize_text(name_cell)
        # Skip section headers ("① 賃貸用建物等" etc.)
        if _RE_SECTION_HEADER.match(norm_name):
            continue
        site_name = _extract_site_name(name_cell)
        if not site_name or site_name.startswith("計") or site_name in {"合計", "小計"}:
            continue
        if skip_hq_row and site_name == "本社":
            continue

        # --- Location ---
        if colmap.location_col is not None and colmap.location_col < len(row):
            loc_cell = row[colmap.location_col] or ""
            location, has_hoka = _extract_location(loc_cell)
        else:
            location, has_hoka = _extract_location(name_cell)

        if not location:
            continue

        # --- Land book value & area ---
        land: float | None = None
        area: float | None = None

        if colmap.land_area_col is not None:
            # 面積と簿価が別列のパターン
            if colmap.land_area_col < len(row):
                area = _parse_land_area_cell(row[colmap.land_area_col] or "")
            if colmap.land_book_col is not None and colmap.land_book_col < len(row):
                land = _parse_number(row[colmap.land_book_col] or "")
        elif colmap.land_book_col is not None and colmap.land_book_col < len(row):
            # 簿価と面積が1セルに一体のパターン (標準形式)
            land, area = _parse_land_cell(row[colmap.land_book_col] or "")

        if land is None:
            continue

        if area is None:
            if location.startswith("東京都"):
                missing_area_errors.append(f"事業所名={site_name}, 所在地={location}, 土地簿価(raw)={land}")
            continue

        out.append(
            FacilityLand(
                site_name=site_name,
                location_short=location,
                land_area_m2=area * colmap.area_scale,
                land_book_value_yen=land * colmap.book_mult,
                location_has_hoka=has_hoka,
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
            if _should_skip_hq_row(txt):
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


def extract_facilities_section_text(pdf_path: str) -> str:
    """有報PDFの「主要な設備の状況」セクションのページテキストを抽出."""
    pages_text: list[str] = []
    in_section = False

    try:
        pdf_file = pdfplumber.open(pdf_path)
    except Exception as e:
        logger.warning("PDF解析失敗(破損の可能性): %s: %s: %s", pdf_path, type(e).__name__, e)
        return ""

    with pdf_file as pdf:
        for page in pdf.pages:
            txt = _normalize_text(page.extract_text() or "")
            if not txt:
                continue
            if (not in_section) and ("主要な設備の状況" in txt) and ("帳簿価額" in txt):
                in_section = True
            if not in_section:
                continue
            pages_text.append(txt)
            if re.search(r"[３3]\s*【\s*設備の新設", txt):
                break

    return "\n\n".join(pages_text)


def _should_skip_hq_row(page_text: str) -> bool:
    txt_compact = re.sub(r"\s+", "", _normalize_text(page_text))
    if ("本社欄に記載の土地" in txt_compact) and ("各所に所在" in txt_compact):
        return True
    if ("本社の土地のなかに鉱業用地" in txt_compact) and ("面積千" in txt_compact):
        return True
    return False
