import argparse
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from src.company_config import load_company_master, save_company_master
from src.company_metadata_fallback import fetch_from_irbank

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = BASE_DIR / "data" / "output"
DEFAULT_OUTPUT_PATH = BASE_DIR / "data" / "ranking" / "ranking_market_cap_ratio.html"
DEFAULT_COMPANY_MASTER_PATH = BASE_DIR / "config" / "company_master.yaml"
CODEX_CHECK_FILE = BASE_DIR / "config" / "codex_check_status.yaml"

logger = logging.getLogger(__name__)


def _open_file(path: Path) -> None:
    """Open a file with the OS default application (cross-platform)."""
    try:
        if sys.platform == "win32":
            import os

            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["qutebrowser", str(path)])
    except OSError:
        logger.warning("ファイルを開けませんでした: %s", path)


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


def normalize_company_name(code: str, raw_name: str, company_master: dict[str, dict[str, Any]]) -> str:
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

    total_rows = [r for r in rows if (r.get("事業所名") or "").strip() == "東京都合計"]
    candidates = total_rows if total_rows else rows

    best_row: dict[str, str] | None = None
    best_ratio = float("-inf")
    for row in candidates:
        ratio = to_float(row.get("時価総額比(実値)", ""))
        if ratio is None:
            ratio = to_float(row.get("時価総額比", ""))
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


def _load_codex_check_status() -> dict[str, int]:
    if not CODEX_CHECK_FILE.exists():
        return {}
    with open(CODEX_CHECK_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return {}
    return {str(k): int(v) for k, v in data.items() if isinstance(v, int)}


def collect_rank_rows(input_dir: Path, company_master: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    codex_check_status = _load_codex_check_status()
    rank_rows: list[dict[str, Any]] = []
    for csv_path in sorted(input_dir.glob("*_output.csv")):
        rows = read_csv_rows(csv_path)
        company_row = pick_company_row(rows)
        if company_row is None:
            continue

        ratio = to_float(company_row.get("時価総額比(実値)", ""))
        if ratio is None:
            ratio = to_float(company_row.get("時価総額比", ""))
        if ratio is None:
            continue

        code = (company_row.get("証券コード") or "").strip()
        company_name = normalize_company_name(code, company_row.get("企業名", ""), company_master)

        check_count = codex_check_status.get(code, 0)
        codex_check_label = f"CODEX_CHECK_{check_count}" if check_count > 0 else ""

        rank_rows.append(
            {
                "証券コード": code,
                "企業名": company_name,
                "有報PDF_URL": company_master.get(code, {}).get("securities_report_pdf_url", "").strip(),
                "時価総額比": ratio,
                "推定土地時価(円)": (company_row.get("推定土地時価(円)") or "").strip(),
                "時価総額(円)": (company_row.get("時価総額(円)") or "").strip(),
                "土地簿価(円)": (company_row.get("土地簿価(円)") or "").strip(),
                "含み益(円)": (company_row.get("含み益(円)") or "").strip(),
                "住所解決タグ": collect_unique_values(rows, "住所解決レベル"),
                "CODEX_CHECK": codex_check_label,
                "タグ件数": count_unique_values(rows, "住所解決レベル"),
                "地価推定信頼度": collect_unique_values(rows, "地価推定信頼度"),
                "異常値警告": collect_unique_values(rows, "異常値警告"),
                "元ファイル": csv_path.name,
            }
        )

    rank_rows.sort(key=lambda r: r["時価総額比"], reverse=True)
    return rank_rows


def _html_pdf_link(code: str, report_pdf_url: str, output_path: Path) -> str:
    import html

    local_pdf_path = BASE_DIR / "data" / "cache" / "pdf" / f"{code}_securities_report.pdf"
    if local_pdf_path.exists():
        href = html.escape(local_pdf_path.as_uri())
        return f'<a href="{href}" target="_blank">{html.escape(local_pdf_path.name)}</a>'
    if report_pdf_url:
        href = html.escape(report_pdf_url)
        return f'<a href="{href}" target="_blank">有報PDF</a>'
    return ""


_HTML_STYLE = """\
<style>
  body { font-family: sans-serif; margin: 20px; background: #fafafa; }
  h1 { font-size: 1.3em; }
  table { border-collapse: collapse; width: 100%; font-size: 0.85em; }
  thead { position: sticky; top: 0; z-index: 1; }
  th { background: #2c3e50; color: #fff; padding: 8px 6px; text-align: left;
       cursor: pointer; user-select: none; white-space: nowrap; }
  th:hover { background: #34495e; }
  td { padding: 6px; border-bottom: 1px solid #ddd; white-space: nowrap; }
  tr:nth-child(even) { background: #f2f2f2; }
  tr:hover { background: #e8f4fd; }
  a { color: #2980b9; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .right { text-align: right; }
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


def write_rank_html(rows: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "順位",
        "証券コード",
        "企業名",
        "有報PDF",
        "時価総額比",
        "推定土地時価(億円)",
        "時価総額(億円)",
        "土地簿価(億円)",
        "含み益(億円)",
        "住所解決タグ",
        "CODEX_CHECK",
        "タグ件数",
        "地価推定信頼度",
        "異常値警告",
        "元ファイル",
    ]
    right_cols = {
        "順位", "時価総額比", "推定土地時価(億円)", "時価総額(億円)",
        "土地簿価(億円)", "含み益(億円)", "タグ件数",
    }

    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("<!DOCTYPE html>\n<html lang=\"ja\">\n<head>\n")
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
            code = (row.get("証券コード") or "").strip()
            report_pdf_url = (row.get("有報PDF_URL") or "").strip()
            pdf_link = _html_pdf_link(code, report_pdf_url, output_path)

            values = [
                (str(i), "順位"),
                (row["証券コード"], "証券コード"),
                (row["企業名"], "企業名"),
                (None, "有報PDF"),  # handled separately
                (f"{row['時価総額比']:.6f}", "時価総額比"),
                (yen_to_oku_display(row["推定土地時価(円)"]), "推定土地時価(億円)"),
                (yen_to_oku_display(row["時価総額(円)"]), "時価総額(億円)"),
                (yen_to_oku_display(row["土地簿価(円)"]), "土地簿価(億円)"),
                (yen_to_oku_display(row["含み益(円)"]), "含み益(億円)"),
                (row.get("住所解決タグ", ""), "住所解決タグ"),
                (row.get("CODEX_CHECK", ""), "CODEX_CHECK"),
                (str(row.get("タグ件数", 0)), "タグ件数"),
                (row.get("地価推定信頼度", ""), "地価推定信頼度"),
                (row.get("異常値警告", ""), "異常値警告"),
                (row["元ファイル"], "元ファイル"),
            ]

            f.write("<tr>\n")
            for val, header in values:
                cls = ' class="right"' if header in right_cols else ""
                if header == "有報PDF":
                    f.write(f"  <td{cls}>{pdf_link}</td>\n")
                else:
                    f.write(f"  <td{cls}>{escape_html_cell(val)}</td>\n")
            f.write("</tr>\n")

        f.write("</tbody>\n</table>\n")
        f.write(_HTML_SORT_SCRIPT)
        f.write("</body>\n</html>\n")


def _resolve_missing_names(rank_rows: list[dict[str, Any]], company_master: dict[str, dict[str, Any]]) -> None:
    """企業名がtickerコードのままの行をIRBankから名前解決し、company_masterに保存する."""
    from concurrent.futures import ThreadPoolExecutor

    unresolved = [(i, row) for i, row in enumerate(rank_rows) if row["企業名"].replace(" ", "") == row["証券コード"]]
    if not unresolved:
        return

    codes = [row["証券コード"] for _, row in unresolved]
    print(f"IRBankから企業名を取得中... ({len(codes)} 社)")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(fetch_from_irbank, codes))

    updated = 0
    for (idx, row), meta in zip(unresolved, results):
        if meta.company_name:
            rank_rows[idx]["企業名"] = meta.company_name
            code = row["証券コード"]
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
) -> None:
    resolved_input_dir = Path(input_dir) if input_dir else DEFAULT_INPUT_DIR
    resolved_output_path = Path(output_path) if output_path else DEFAULT_OUTPUT_PATH
    if not resolved_output_path.is_absolute():
        resolved_output_path = BASE_DIR / resolved_output_path

    company_master = load_company_master(str(DEFAULT_COMPANY_MASTER_PATH))
    rank_rows = collect_rank_rows(resolved_input_dir, company_master)
    _resolve_missing_names(rank_rows, company_master)
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
