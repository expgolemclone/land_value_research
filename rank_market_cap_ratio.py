import argparse
import csv
import os
from pathlib import Path
from typing import Any

from src.company_config import load_company_master

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = BASE_DIR / "data" / "output"
DEFAULT_OUTPUT_PATH = DEFAULT_INPUT_DIR / "ranking_market_cap_ratio.md"
DEFAULT_EXCLUDED_OUTPUT_PATH = DEFAULT_INPUT_DIR / "ranking_market_cap_ratio_excluded.md"
DEFAULT_COMPANY_MASTER_PATH = BASE_DIR / "config" / "company_master.yaml"


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    encodings = ["utf-8-sig", "cp932"]
    for enc in encodings:
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("unknown", b"", 0, 1, f"CSVを読めませんでした: {path}")


def read_optional_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    return read_csv_rows(path)


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


def load_excluded_rows(input_dir: Path) -> list[dict[str, str]]:
    return read_optional_csv_rows(input_dir / "anomaly_excluded_companies.csv")


def collect_excluded_codes(excluded_rows: list[dict[str, str]]) -> set[str]:
    return {(row.get("証券コード") or "").strip() for row in excluded_rows if (row.get("証券コード") or "").strip()}


def collect_rank_rows(
    input_dir: Path, company_master: dict[str, dict[str, Any]], excluded_codes: set[str]
) -> list[dict[str, Any]]:
    rank_rows: list[dict[str, Any]] = []
    for csv_path in sorted(input_dir.glob("*_output.csv")):
        rows = read_csv_rows(csv_path)
        company_row = pick_company_row(rows)
        if company_row is None:
            continue

        ratio = to_float(company_row.get("時価総額比", ""))
        if ratio is None:
            continue

        code = (company_row.get("証券コード") or "").strip()
        if code in excluded_codes:
            continue
        company_name = normalize_company_name(code, company_row.get("企業名", ""), company_master)

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
                "タグ件数": count_unique_values(rows, "住所解決レベル"),
                "異常値警告": collect_unique_values(rows, "異常値警告"),
                "元ファイル": csv_path.name,
            }
        )

    rank_rows.sort(key=lambda r: r["時価総額比"], reverse=True)
    return rank_rows


def write_rank_markdown(rows: list[dict[str, Any]], output_path: Path) -> None:
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
        "タグ件数",
        "異常値警告",
        "元ファイル",
    ]
    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("| " + " | ".join(headers) + " |\n")
        f.write("| " + " | ".join(["---"] * len(headers)) + " |\n")
        for i, row in enumerate(rows, start=1):
            report_pdf_url = (row.get("有報PDF_URL") or "").strip()
            code = (row.get("証券コード") or "").strip()
            local_pdf_path = BASE_DIR / "data" / "cache" / "pdf" / f"{code}_securities_report.pdf"
            if local_pdf_path.exists():
                report_pdf_link = to_md_link(output_path, local_pdf_path)
            else:
                report_pdf_link = f"[有報PDF]({report_pdf_url})" if report_pdf_url else ""
            values = [
                str(i),
                row["証券コード"],
                row["企業名"],
                report_pdf_link,
                f"{row['時価総額比']:.6f}",
                yen_to_oku_display(row["推定土地時価(円)"]),
                yen_to_oku_display(row["時価総額(円)"]),
                yen_to_oku_display(row["土地簿価(円)"]),
                yen_to_oku_display(row["含み益(円)"]),
                row.get("住所解決タグ", ""),
                str(row.get("タグ件数", 0)),
                row.get("異常値警告", ""),
                row["元ファイル"],
            ]
            f.write("| " + " | ".join(values) + " |\n")


def to_md_rel_path(base_path: Path, target_path: Path) -> str:
    rel = os.path.relpath(target_path, start=base_path.parent)
    return rel.replace("\\", "/")


def to_md_link(base_path: Path, target_path: Path) -> str:
    return f"[{target_path.name}]({to_md_rel_path(base_path, target_path)})"


def find_related_anomaly_csvs(input_dir: Path) -> list[Path]:
    related: list[Path] = []
    if input_dir.exists():
        direct = input_dir / "anomaly_excluded_companies.csv"
        if direct.exists():
            related.append(direct)

        for path in sorted(input_dir.parent.glob("output*/anomaly_excluded_companies.csv")):
            if path not in related:
                related.append(path)
    return related


def get_company_codes(rows: list[dict[str, str]]) -> list[str]:
    seen: set[str] = set()
    codes: list[str] = []
    for row in rows:
        code = (row.get("証券コード") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        codes.append(code)
    return codes


def build_company_related_links(code: str, base_markdown_path: Path, input_dir: Path) -> tuple[str, str]:
    pdf_path = BASE_DIR / "data" / "cache" / "pdf" / f"{code}_securities_report.pdf"
    company_csv_path = input_dir / f"{code}_output.csv"
    anomaly_csv_path = input_dir / "anomaly_excluded_companies.csv"

    pdf_link = to_md_link(base_markdown_path, pdf_path) if pdf_path.exists() else ""

    csv_links: list[str] = []
    if company_csv_path.exists():
        csv_links.append(to_md_link(base_markdown_path, company_csv_path))
    if anomaly_csv_path.exists():
        csv_links.append(to_md_link(base_markdown_path, anomaly_csv_path))
    csv_link = " / ".join(csv_links)
    return pdf_link, csv_link


def write_open_related_files_script(rows: list[dict[str, str]], input_dir: Path, excluded_output_path: Path) -> Path:
    script_path = excluded_output_path.parent / "open_excluded_related_files.ps1"

    targets: list[Path] = [excluded_output_path]
    targets.extend(find_related_anomaly_csvs(input_dir))

    for code in get_company_codes(rows):
        pdf_path = BASE_DIR / "data" / "cache" / "pdf" / f"{code}_securities_report.pdf"
        if pdf_path.exists():
            targets.append(pdf_path)

        company_csv_path = input_dir / f"{code}_output.csv"
        if company_csv_path.exists():
            targets.append(company_csv_path)

    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in targets:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)

    script_path.parent.mkdir(parents=True, exist_ok=True)
    with script_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("$targets = @(\n")
        for path in deduped:
            escaped_path = str(path).replace("'", "''")
            f.write(f"    '{escaped_path}',\n")
        f.write(")\n\n")
        f.write("foreach ($path in $targets) {\n")
        f.write("    if (Test-Path $path) {\n")
        f.write("        Start-Process $path\n")
        f.write("    } else {\n")
        f.write('        Write-Host "not found: $path"\n')
        f.write("    }\n")
        f.write("}\n")

    return script_path


def write_excluded_markdown(rows: list[dict[str, str]], output_path: Path, input_dir: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    open_script_path = write_open_related_files_script(rows, input_dir, output_path)
    related_anomaly_csvs = find_related_anomaly_csvs(input_dir)

    def excluded_ratio(row: dict[str, str]) -> float:
        ratio = to_float(row.get("時価総額比(実値)", ""))
        return ratio if ratio is not None else float("-inf")

    sorted_rows = sorted(
        rows,
        key=excluded_ratio,
        reverse=True,
    )
    headers = [
        "順位",
        "証券コード",
        "企業名",
        "時価総額比",
        "推定土地時価(億円)",
        "土地簿価(億円)",
        "事業所名",
        "理由コード",
        "理由詳細",
        "土地面積(m2)",
        "地価単価(円/m2)",
        "評価倍率(実値)",
        "閾値_地価単価(円/m2)",
        "閾値_土地面積(m2)",
        "閾値_評価倍率",
        "同一住所件数",
        "同一住所合計面積(m2)",
        "閾値_同一住所件数",
        "閾値_同一住所合計面積(m2)",
        "住所",
        "住所取得元",
        "住所解決レベル",
        "関連PDF",
        "関連CSV",
    ]
    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("## 手動確認用リンク\n\n")
        f.write(f"- [関連ファイルを一括で開く(ps1)]({to_md_rel_path(output_path, open_script_path)})\n")
        for csv_path in related_anomaly_csvs:
            folder_name = csv_path.parent.name
            f.write(f"- [除外一覧CSV({folder_name})]({to_md_rel_path(output_path, csv_path)})\n")
        f.write("\n")
        f.write("| " + " | ".join(headers) + " |\n")
        f.write("| " + " | ".join(["---"] * len(headers)) + " |\n")
        for i, row in enumerate(sorted_rows, start=1):
            code = (row.get("証券コード") or "").strip()
            pdf_link, csv_link = build_company_related_links(code, output_path, input_dir)
            ratio = to_float(row.get("時価総額比(実値)", ""))
            values = [
                str(i),
                code,
                (row.get("企業名") or "").strip(),
                f"{ratio:.6f}" if ratio is not None else "",
                yen_to_oku_display(row.get("推定土地時価(円)", "")),
                yen_to_oku_display(row.get("土地簿価(円)", "")),
                (row.get("事業所名") or "").strip(),
                (row.get("理由コード") or "").strip(),
                (row.get("理由詳細") or "").strip(),
                (row.get("土地面積(m2)") or "").strip(),
                (row.get("地価単価(円/m2)") or "").strip(),
                (row.get("評価倍率(実値)") or "").strip(),
                (row.get("閾値_地価単価(円/m2)") or "").strip(),
                (row.get("閾値_土地面積(m2)") or "").strip(),
                (row.get("閾値_評価倍率") or "").strip(),
                (row.get("同一住所件数") or "").strip(),
                (row.get("同一住所合計面積(m2)") or "").strip(),
                (row.get("閾値_同一住所件数") or "").strip(),
                (row.get("閾値_同一住所合計面積(m2)") or "").strip(),
                (row.get("住所") or "").strip(),
                (row.get("住所取得元") or "").strip(),
                (row.get("住所解決レベル") or "").strip(),
                pdf_link,
                csv_link,
            ]
            f.write("| " + " | ".join(values) + " |\n")
    return open_script_path


def main() -> None:
    parser = argparse.ArgumentParser(description="data/output配下の時価総額比ランキングMarkdownを生成する")
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR), help="企業別CSVがあるフォルダ")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help="ランキングMarkdownの出力パス",
    )
    parser.add_argument(
        "--excluded-output",
        default=str(DEFAULT_EXCLUDED_OUTPUT_PATH),
        help="除外銘柄Markdownの出力パス",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_path = Path(args.output)
    excluded_output_path = Path(args.excluded_output)
    if not output_path.is_absolute():
        output_path = BASE_DIR / output_path
    if not excluded_output_path.is_absolute():
        excluded_output_path = BASE_DIR / excluded_output_path
    company_master = load_company_master(str(DEFAULT_COMPANY_MASTER_PATH))
    excluded_rows = load_excluded_rows(input_dir)
    excluded_codes = collect_excluded_codes(excluded_rows)
    rank_rows = collect_rank_rows(input_dir, company_master, excluded_codes)
    write_rank_markdown(rank_rows, output_path)
    open_script_path = write_excluded_markdown(excluded_rows, excluded_output_path, input_dir)
    print(f"written: {output_path} ({len(rank_rows)} rows)")
    print(f"written: {excluded_output_path} ({len(excluded_rows)} rows)")
    print(f"written: {open_script_path}")

    os.startfile(output_path)
    os.startfile(excluded_output_path)


if __name__ == "__main__":
    main()
