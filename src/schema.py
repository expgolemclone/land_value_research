"""Single source of truth for all column schemas.

Every script that reads or writes CSV/HTML columns MUST import definitions
from this module.  Adding, renaming, or reordering a column here is the
ONLY change needed — downstream breakage is caught by
tests/test_schema_consistency.py.
"""

from __future__ import annotations

from typing import TypedDict

# ── 企業別出力 CSV (33列, 順序が意味を持つ) ──────────────────

OUTPUT_COLUMNS: tuple[str, ...] = (
    "証券コード",
    "企業名",
    "事業所名",
    "住所",
    "住所取得元",
    "住所取得元URL",
    "住所解決レベル",
    "土地面積(m2)",
    "地価単価(円/m2)",
    "地価単価補正係数",
    "住所解像度補正係数",
    "地価単価算出方法",
    "基準用途区分",
    "最近傍用途区分",
    "公示点ID",
    "公示点距離(m)",
    "k近傍ID",
    "k近傍用途区分",
    "k近傍距離(m)",
    "k近傍単価(円/m2)",
    "k近傍距離分散(m2)",
    "k近傍最遠距離(m)",
    "地価推定信頼度スコア",
    "地価推定信頼度",
    "異常値警告",
    "推定土地時価(円)",
    "土地簿価(円)",
    "含み益(円)",
    "評価倍率(実値)",
    "評価倍率",
    "時価総額(円)",
    "時価総額比(実値)",
    "時価総額比",
)

# TypedDict を SSOT から動的生成 (functional syntax — キーに括弧を含むため)
OutputRow = TypedDict("OutputRow", {col: object for col in OUTPUT_COLUMNS})

# ── ランキング HTML テーブルヘッダー (15列) ──────────────────

RANKING_COLUMNS: tuple[str, ...] = (
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
    "調査済",
    "タグ件数",
    "地価推定信頼度",
    "異常値警告",
    "元ファイル",
)

# ── precheck で参照する出力 CSV カラム名 ────────────────────

COL_SITE_NAME = "事業所名"
COL_ADDRESS = "住所"
COL_ADDRESS_SOURCE = "住所取得元"
COL_GEOCODE_LEVEL = "住所解決レベル"
COL_LAND_AREA = "土地面積(m2)"
COL_ANOMALY_WARNING = "異常値警告"
COL_ESTIMATED_VALUE = "推定土地時価(円)"
COL_MARKET_CAP = "時価総額(円)"
COL_BOOK_VALUE = "土地簿価(円)"
COL_UNREALIZED_GAIN = "含み益(円)"
COL_RATIO_RAW = "時価総額比(実値)"
COL_RATIO = "時価総額比"
COL_CONFIDENCE = "地価推定信頼度"
COL_CODE = "証券コード"
COL_COMPANY_NAME = "企業名"
