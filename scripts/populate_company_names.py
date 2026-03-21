"""JPX東証上場銘柄一覧から企業名を取得し company_master.yaml に一括登録する."""

from __future__ import annotations

import importlib
import sys
import tempfile
import urllib.request
from pathlib import Path

import xlrd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

company_config = importlib.import_module("src.company_config")
load_company_master = company_config.load_company_master
save_company_master = company_config.save_company_master

from src.config import COMPANY_MASTER_PATH as _COMPANY_MASTER_PATH

COMPANY_MASTER_PATH = str(_COMPANY_MASTER_PATH)
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

    # Find header row and column indices
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
        # xlrd may read numeric codes as float
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

    master = load_company_master(COMPANY_MASTER_PATH)
    updated = 0
    already = 0
    not_in_master = 0

    for code, name in jpx_names.items():
        if code in master:
            if "company_name" not in master[code]:
                master[code]["company_name"] = name
                updated += 1
            else:
                already += 1
        else:
            # company_master にエントリ自体がないコードも追加
            master[code] = {"company_name": name}
            updated += 1
            not_in_master += 1

    save_company_master(COMPANY_MASTER_PATH, master)
    print(f"更新: {updated} 件 (うち新規エントリ: {not_in_master} 件)")
    print(f"既存company_name: {already} 件 (スキップ)")
    print(f"company_master.yaml 合計: {len(master)} エントリ")


if __name__ == "__main__":
    main()
