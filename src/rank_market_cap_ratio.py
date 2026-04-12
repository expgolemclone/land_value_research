from __future__ import annotations

import argparse
import functools
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from src.company_config import CompanyMaster, load_company_master, save_company_master
from src.company_metadata_fallback import fetch_from_irbank

if TYPE_CHECKING:
    from src.browser import BrowserService
    from src.stealth import ProxyPool
from src.config import (
    COMPANY_MASTER_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_RANKING_PATH,
    PDF_CACHE_DIR,
    PROJECT_ROOT,
)
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
    RANK_COL_BOOK_VALUE_OKU,
    RANK_COL_ESTIMATED_VALUE_OKU,
    RANK_COL_GEOCODE_TAG,
    RANK_COL_MARKET_CAP_OKU,
    RANK_COL_MEMO,
    RANK_COL_PDF,
    RANK_COL_RANK,
    RANK_COL_SOURCE_FILE,
    RANK_COL_TAG_COUNT,
    RANK_COL_UNREALIZED_GAIN_OKU,
    RANKING_COLUMNS,
)

BASE_DIR = PROJECT_ROOT
DEFAULT_INPUT_DIR = DEFAULT_OUTPUT_DIR
DEFAULT_OUTPUT_PATH = DEFAULT_RANKING_PATH
DEFAULT_COMPANY_MASTER_PATH = COMPANY_MASTER_PATH
DOCS_DIR = PROJECT_ROOT / "split-address"

logger = logging.getLogger(__name__)


def _open_file(path: Path) -> bool:
    """Open a file with the OS default application (best-effort)."""
    resolved_path = path.resolve()
    logger.info("HTMLを開きます: %s", resolved_path)
    try:
        if sys.platform == "win32":
            try:
                os.startfile(resolved_path)
                return True
            except OSError as exc:
                logger.warning("os.startfileで開けませんでした。cmd /c start を試します: %s (%s)", resolved_path, exc)
                subprocess.Popen(["cmd", "/c", "start", "", str(resolved_path)])
                return True
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(resolved_path)])
            return True
        subprocess.Popen(["qutebrowser", str(resolved_path)])
        return True
    except OSError as exc:
        logger.warning("ファイルを開けませんでした: %s (%s)", resolved_path, exc)
        return False


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    import csv

    encodings = ["utf-8-sig", "cp932"]
    for enc in encodings:
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("unknown", b"", 0, 1, f"CSVを読めませんでした: {path}")


def to_float(raw: str) -> float | None:
    s = (raw or "").strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def yen_to_oku_display(raw: str) -> str:
    value = to_float(raw)
    if value is None:
        return ""
    return f"{value / 100_000_000:,.2f}"


def normalize_company_name(code: str, raw_name: str, company_master: CompanyMaster) -> str:
    name = (raw_name or "").strip()
    normalized_code = (code or "").strip()
    if not normalized_code:
        return name

    if not name:
        return company_master.get(normalized_code, {}).get("company_name", "")

    compact_name = name.replace(" ", "")
    if compact_name == normalized_code:
        return company_master.get(normalized_code, {}).get("company_name", name)

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


def escape_html_cell(value: object) -> str:
    import html

    s = str(value if value is not None else "")
    s = html.escape(s)
    s = s.replace("\r", "").replace("\n", "<br>")
    return s


def _md_to_html(text: str) -> str:
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
        # リンク [text](url)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" target="_blank">\1</a>', s)
        return s

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

        # 空行
        if not stripped:
            _close_list()
            _close_table()
            continue

        # 見出し
        m = re.match(r"^(#{1,4})\s+(.*)", stripped)
        if m:
            _close_list()
            _close_table()
            level = min(len(m.group(1)) + 2, 6)  # # → h3, ## → h4
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            continue

        # テーブル区切り行（| --- | --- |）
        if re.match(r"^\|[\s\-:|]+\|$", stripped):
            table_has_header = True
            continue

        # テーブル行
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
            if not table_has_header:
                # まだヘッダ区切りが来ていない → thead の続き扱い
                pass
            out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
            continue

        # リスト項目
        m = re.match(r"^[-*]\s+(.*)", stripped)
        if m:
            _close_table()
            if not in_ul:
                in_ul = True
                out.append("<ul>")
            out.append(f"<li>{_inline(m.group(1))}</li>")
            continue

        # 通常テキスト
        _close_list()
        _close_table()
        out.append(f"<p>{_inline(stripped)}</p>")

    _close_list()
    _close_table()
    return "\n".join(out)


def collect_rank_rows(input_dir: Path, company_master: CompanyMaster) -> list[dict[str, str]]:
    rank_rows: list[dict[str, str]] = []
    for csv_path in sorted(input_dir.glob("*_output.csv")):
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
        company_name = normalize_company_name(code, company_row.get(COL_COMPANY_NAME, ""), company_master)

        docs_path = DOCS_DIR / f"{code}.md"
        docs_content = ""
        if docs_path.exists():
            try:
                docs_content = docs_path.read_text(encoding="utf-8")
            except OSError:
                pass

        rank_rows.append(
            {
                COL_CODE: code,
                COL_COMPANY_NAME: company_name,
                "有報PDF_URL": company_master.get(code, {}).get("securities_report_pdf_url", "").strip(),
                COL_RATIO: ratio,
                COL_ESTIMATED_VALUE: (company_row.get(COL_ESTIMATED_VALUE) or "").strip(),
                COL_MARKET_CAP: (company_row.get(COL_MARKET_CAP) or "").strip(),
                COL_BOOK_VALUE: (company_row.get(COL_BOOK_VALUE) or "").strip(),
                COL_UNREALIZED_GAIN: (company_row.get(COL_UNREALIZED_GAIN) or "").strip(),
                RANK_COL_GEOCODE_TAG: collect_unique_values(rows, COL_GEOCODE_LEVEL),
                RANK_COL_MEMO: docs_content,
                RANK_COL_TAG_COUNT: count_unique_values(rows, COL_GEOCODE_LEVEL),
                COL_CONFIDENCE: collect_unique_values(rows, COL_CONFIDENCE),
                COL_ANOMALY_WARNING: collect_unique_values(rows, COL_ANOMALY_WARNING),
                RANK_COL_SOURCE_FILE: csv_path.name,
            }
        )

    rank_rows.sort(key=lambda r: r[COL_RATIO], reverse=True)
    return rank_rows


def _html_pdf_link(code: str, report_pdf_url: str, output_path: Path) -> str:
    import html

    local_pdf_path = PDF_CACHE_DIR / f"{code}_securities_report.pdf"
    if local_pdf_path.exists():
        href = html.escape(local_pdf_path.as_uri())
        return f'<a href="{href}" target="_blank">{html.escape(local_pdf_path.name)}</a>'
    if report_pdf_url:
        href = html.escape(report_pdf_url)
        return f'<a href="{href}" target="_blank">有報PDF</a>'
    return ""


_HTML_STYLE = """\
<style>
  body { font-family: sans-serif; margin: 20px; background: #1a1a2e; color: #e0e0e0; }
  h1 { font-size: 1.3em; color: #e0e0e0; }
  table { border-collapse: collapse; width: 100%; font-size: 0.85em; }
  thead { position: sticky; top: 0; z-index: 1; }
  th { background: #16213e; color: #e0e0e0; padding: 8px 6px; text-align: left;
       cursor: pointer; user-select: none; white-space: nowrap; }
  th:hover { background: #0f3460; }
  td { padding: 6px; border-bottom: 1px solid #2a2a4a; white-space: nowrap; }
  tr:nth-child(even) { background: #1e1e3a; }
  tr:hover { background: #2a2a5a; }
  a { color: #5dade2; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .right { text-align: right; }
  .docs-btn { background: #1a2744; border: 1px solid #5dade2; color: #5dade2; padding: 3px 12px;
    border-radius: 4px; cursor: pointer; font-size: 0.85em; font-weight: bold; white-space: nowrap; }
  .docs-btn:hover { background: #5dade2; color: #0d1117; }
  #docs-modal { position: fixed; inset: 0; z-index: 100; display: flex;
    align-items: center; justify-content: center; }
  #docs-modal.hidden { display: none; }
  .modal-backdrop { position: absolute; inset: 0; background: rgba(0,0,0,0.7); }
  .modal-content { position: relative; width: 90vw; max-width: 1100px; max-height: 90vh;
    overflow-y: auto; background: #0d1117; color: #c9d1d9; border: 1px solid #444c6a;
    border-radius: 12px; padding: 32px 44px; box-shadow: 0 12px 40px rgba(0,0,0,0.8);
    font-size: 0.95em; line-height: 1.7; }
  .modal-close { position: absolute; top: 10px; right: 16px; background: none; border: none;
    color: #888; font-size: 1.6em; cursor: pointer; line-height: 1; }
  .modal-close:hover { color: #e0e0e0; }
  .docs-body h3 { font-size: 1.2em; color: #e0e0e0; margin: 16px 0 8px;
    border-bottom: 1px solid #2a2a4a; padding-bottom: 4px; }
  .docs-body h4 { font-size: 1.05em; color: #d0d0d0; margin: 12px 0 6px; }
  .docs-body h5 { font-size: 1em; color: #c0c0c0; margin: 10px 0 4px; }
  .docs-body ul { margin: 6px 0 6px 20px; padding: 0; }
  .docs-body li { margin: 3px 0; }
  .docs-body p { margin: 6px 0; }
  .docs-body code { background: #1a1a2e; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; color: #f0c674; }
  .docs-body a { color: #5dade2; }
  .docs-body .md-table { width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 0.9em; }
  .docs-body .md-table th { background: #16213e; padding: 6px 10px; text-align: left;
    border-bottom: 2px solid #444c6a; white-space: normal; }
  .docs-body .md-table td { padding: 5px 10px; border-bottom: 1px solid #2a2a4a; white-space: normal; }
</style>
"""

_HTML_SORT_SCRIPT = """\
<script>
document.querySelectorAll('th').forEach((th, idx) => {
  th.addEventListener('click', () => {
    const table = th.closest('table');
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const dir = th.dataset.dir === 'asc' ? 'desc' : 'asc';
    table.querySelectorAll('th').forEach(h => delete h.dataset.dir);
    th.dataset.dir = dir;
    rows.sort((a, b) => {
      let av = a.cells[idx].textContent.trim().replace(/,/g, '');
      let bv = b.cells[idx].textContent.trim().replace(/,/g, '');
      const an = parseFloat(av), bn = parseFloat(bv);
      if (!isNaN(an) && !isNaN(bn)) return dir === 'asc' ? an - bn : bn - an;
      return dir === 'asc' ? av.localeCompare(bv, 'ja') : bv.localeCompare(av, 'ja');
    });
    rows.forEach(r => tbody.appendChild(r));
  });
});
</script>
"""

_HTML_MODAL_SCRIPT = """\
<div id="docs-modal" class="hidden">
  <div class="modal-backdrop"></div>
  <div class="modal-content">
    <button class="modal-close">&times;</button>
    <div class="docs-body" id="docs-modal-body"></div>
  </div>
</div>
<script>
(function(){
  const modal = document.getElementById('docs-modal');
  const body = document.getElementById('docs-modal-body');
  const backdrop = modal.querySelector('.modal-backdrop');
  const closeBtn = modal.querySelector('.modal-close');
  function open(idx) {
    const tpl = document.getElementById('docs-' + idx);
    if (!tpl) return;
    body.innerHTML = tpl.innerHTML;
    modal.classList.remove('hidden');
  }
  function close() { modal.classList.add('hidden'); body.innerHTML = ''; }
  document.addEventListener('click', function(e) {
    const btn = e.target.closest('.docs-btn');
    if (btn) { open(btn.dataset.idx); return; }
  });
  backdrop.addEventListener('click', close);
  closeBtn.addEventListener('click', close);
  document.addEventListener('keydown', function(e) { if (e.key === 'Escape') close(); });
})();
</script>
"""


def write_rank_html(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    headers = list(RANKING_COLUMNS)
    right_cols = {
        RANK_COL_RANK,
        COL_RATIO,
        RANK_COL_ESTIMATED_VALUE_OKU,
        RANK_COL_MARKET_CAP_OKU,
        RANK_COL_BOOK_VALUE_OKU,
        RANK_COL_UNREALIZED_GAIN_OKU,
        RANK_COL_TAG_COUNT,
    }

    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write('<!DOCTYPE html>\n<html lang="ja">\n<head>\n')
        f.write('<meta charset="utf-8">\n')
        f.write("<title>時価総額比ランキング</title>\n")
        f.write(_HTML_STYLE)
        f.write("</head>\n<body>\n")
        f.write(f"<h1>時価総額比ランキング ({len(rows)} 社)</h1>\n")
        f.write("<table>\n<thead><tr>\n")
        for h in headers:
            f.write(f"  <th>{escape_html_cell(h)}</th>\n")
        f.write("</tr></thead>\n<tbody>\n")

        for i, row in enumerate(rows, start=1):
            code = (row.get(COL_CODE) or "").strip()
            report_pdf_url = (row.get("有報PDF_URL") or "").strip()
            pdf_link = _html_pdf_link(code, report_pdf_url, output_path)

            docs_content = row.get(RANK_COL_MEMO, "")

            values = [
                (str(i), RANK_COL_RANK),
                (row[COL_CODE], COL_CODE),
                (row[COL_COMPANY_NAME], COL_COMPANY_NAME),
                (None, RANK_COL_MEMO),  # handled separately
                (f"{row[COL_RATIO]:.6f}", COL_RATIO),
                (row.get(RANK_COL_GEOCODE_TAG, ""), RANK_COL_GEOCODE_TAG),
                (row.get(COL_CONFIDENCE, ""), COL_CONFIDENCE),
                (row.get(COL_ANOMALY_WARNING, ""), COL_ANOMALY_WARNING),
                (None, RANK_COL_PDF),  # handled separately
                (yen_to_oku_display(row[COL_ESTIMATED_VALUE]), RANK_COL_ESTIMATED_VALUE_OKU),
                (yen_to_oku_display(row[COL_MARKET_CAP]), RANK_COL_MARKET_CAP_OKU),
                (yen_to_oku_display(row[COL_BOOK_VALUE]), RANK_COL_BOOK_VALUE_OKU),
                (yen_to_oku_display(row[COL_UNREALIZED_GAIN]), RANK_COL_UNREALIZED_GAIN_OKU),
                (str(row.get(RANK_COL_TAG_COUNT, 0)), RANK_COL_TAG_COUNT),
                (row[RANK_COL_SOURCE_FILE], RANK_COL_SOURCE_FILE),
            ]

            f.write("<tr>\n")
            for val, header in values:
                cls = ' class="right"' if header in right_cols else ""
                if header == RANK_COL_MEMO:
                    if docs_content:
                        rendered = _md_to_html(docs_content)
                        f.write(f'  <td><button class="docs-btn" data-idx="{i}">\U0001f4cb 調査メモ</button>')
                        f.write(f'<template id="docs-{i}">{rendered}</template></td>\n')
                    else:
                        f.write("  <td></td>\n")
                elif header == RANK_COL_PDF:
                    f.write(f"  <td{cls}>{pdf_link}</td>\n")
                else:
                    f.write(f"  <td{cls}>{escape_html_cell(val)}</td>\n")
            f.write("</tr>\n")

        f.write("</tbody>\n</table>\n")
        f.write(_HTML_SORT_SCRIPT)
        f.write(_HTML_MODAL_SCRIPT)
        f.write("</body>\n</html>\n")


def _resolve_missing_names(
    rank_rows: list[dict[str, str]],
    company_master: dict[str, dict[str, str]],
    *,
    browser: BrowserService,
    pool: ProxyPool | None = None,
) -> None:
    """企業名がtickerコードのままの行をIRBankから名前解決し、company_masterに保存する."""
    from concurrent.futures import ThreadPoolExecutor

    unresolved: list[tuple[int, dict[str, str]]] = [
        (i, row) for i, row in enumerate(rank_rows) if row[COL_COMPANY_NAME].replace(" ", "") == row[COL_CODE]
    ]
    if not unresolved:
        return

    codes: list[str] = [row[COL_CODE] for _, row in unresolved]
    print(f"IRBankから企業名を取得中... ({len(codes)} 社)")

    with ThreadPoolExecutor(max_workers=8) as executor:
        fetch_fn = functools.partial(fetch_from_irbank, browser=browser, pool=pool)
        results = list(executor.map(fetch_fn, codes))

    updated = 0
    for (idx, row), meta in zip(unresolved, results):
        if meta.company_name:
            rank_rows[idx][COL_COMPANY_NAME] = meta.company_name
            code = row[COL_CODE]
            if code not in company_master:
                company_master[code] = {}
            company_master[code]["company_name"] = meta.company_name
            updated += 1

    if updated:
        save_company_master(str(DEFAULT_COMPANY_MASTER_PATH), company_master)
        print(f"企業名を {updated} 件取得し company_master.yaml に保存しました")


def generate_ranking(
    input_dir: Path | str | None = None,
    output_path: Path | str | None = None,
    *,
    open_files: bool = True,
    browser: BrowserService | None = None,
    pool: ProxyPool | None = None,
) -> None:
    """Generate ranking HTML and optionally request the OS to open it."""
    resolved_input_dir: Path = Path(input_dir) if input_dir else DEFAULT_INPUT_DIR
    resolved_output_path: Path = Path(output_path) if output_path else DEFAULT_OUTPUT_PATH
    if not resolved_output_path.is_absolute():
        resolved_output_path = BASE_DIR / resolved_output_path

    company_master = load_company_master(str(DEFAULT_COMPANY_MASTER_PATH))
    rank_rows = collect_rank_rows(resolved_input_dir, company_master)
    if browser is not None:
        _resolve_missing_names(rank_rows, company_master, browser=browser, pool=pool)
    write_rank_html(rank_rows, resolved_output_path)
    print(f"written: {resolved_output_path} ({len(rank_rows)} rows)")

    if open_files:
        _open_file(resolved_output_path)


def main() -> None:
    import shtab

    parser = argparse.ArgumentParser(
        prog="land-value-rank",
        description="data/ranking配下の時価総額比ランキングHTMLを生成する",
    )
    shtab.add_argument_to(parser)
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR), help="企業別CSVがあるフォルダ")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help="ランキングHTMLの出力パス",
    )
    args = parser.parse_args()
    generate_ranking(
        input_dir=args.input_dir,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
