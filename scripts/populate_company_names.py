"""JPX東証上場銘柄一覧から企業名を取得し land.db に一括登録する."""

from __future__ import annotations

import sys
import tempfile
import urllib.request
from pathlib import Path

import xlrd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.company_store import connect_company_db, load_company_directory, merge_company_record  # noqa: E402
from src.stock_db_sync import load_stock_db_company_metadata  # noqa: E402

JPX_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"


def download_jpx_xls() -> bytes:
    req = urllib.request.Request(
        JPX_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; land_value_research/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def parse_jpx_xls(data: bytes) -> dict[str, str]:
    """Parse JPX xls and return {code: company_name}."""
    with tempfile.NamedTemporaryFile(suffix=".xls", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    wb = xlrd.open_workbook(tmp_path)
    sheet = wb.sheet_by_index(0)

    code_col = None
    name_col = None
    header_row = 0
    for row_idx in range(min(5, sheet.nrows)):
        for col_idx in range(sheet.ncols):
            val = str(sheet.cell_value(row_idx, col_idx)).strip()
            if val == "コード":
                code_col = col_idx
                header_row = row_idx
            elif val == "銘柄名":
                name_col = col_idx

    if code_col is None or name_col is None:
        raise ValueError(f"JPX XLSのヘッダーが見つかりません (code_col={code_col}, name_col={name_col})")

    result: dict[str, str] = {}
    for row_idx in range(header_row + 1, sheet.nrows):
        raw_code = sheet.cell_value(row_idx, code_col)
        if isinstance(raw_code, float):
            code = str(int(raw_code))
        else:
            code = str(raw_code).strip()
        name = str(sheet.cell_value(row_idx, name_col)).strip()
        if code and name:
            result[code] = name

    Path(tmp_path).unlink(missing_ok=True)
    return result


def main() -> None:
    print("JPX東証上場銘柄一覧をダウンロード中...")
    data = download_jpx_xls()
    print(f"ダウンロード完了 ({len(data):,} bytes)")

    jpx_names = parse_jpx_xls(data)
    print(f"JPX銘柄数: {len(jpx_names)}")

    conn = connect_company_db()
    records = load_company_directory(conn)
    updated = 0
    already = 0
    new_entries = 0

    # stock.db から企業名を事前補完
    stock_meta = load_stock_db_company_metadata(jpx_names.keys())
    stock_synced = 0
    for code in list(jpx_names.keys()):
        meta = stock_meta.get(code)
        if meta and meta.company_name:
            current_name = records.get(code, {}).get("company_name", "")
            if not current_name:
                records[code] = merge_company_record(conn, code, company_name=meta.company_name)
                stock_synced += 1
                del jpx_names[code]
                new_entries += 1
            else:
                del jpx_names[code]
                already += 1
    if stock_synced:
        conn.commit()
        print(f"stock.db 同期: {stock_synced} 件の企業名を補完")

    if not jpx_names:
        print("stock.db で全件補完済み。JPX登録をスキップ")
        print(f"land.db 合計: {len(records)} エントリ")
        conn.close()
        return

    try:
        for code, name in jpx_names.items():
            existed_before = code in records
            current_name = records.get(code, {}).get("company_name", "")
            if current_name:
                already += 1
                continue
            records[code] = merge_company_record(conn, code, company_name=name)
            updated += 1
            if not existed_before:
                new_entries += 1

        conn.commit()
    finally:
        conn.close()

    print(f"更新: {updated} 件 (うち新規エントリ: {new_entries} 件)")
    print(f"既存 company_name: {already} 件 (スキップ)")
    print(f"land.db 合計: {len(records)} エントリ")


if __name__ == "__main__":
    main()
