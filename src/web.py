"""Web UI integration: serves land value ranking via stock_web_ui."""

from __future__ import annotations

import json
from pathlib import Path

from stock_web_ui.config import ServerConfig
from stock_web_ui.handler import ApiHandler, json_route
from stock_web_ui.page import IndexPage
from stock_web_ui.serve import serve as _serve

from src.config import DEFAULT_OUTPUT_DIR, PROJECT_ROOT
from src.rank_market_cap_ratio import _md_to_html, collect_rank_rows, to_float
from src.company_store import connect_company_db, load_company_directory

_PROJECT_ROOT: Path = PROJECT_ROOT
_DOCS_DIR: Path = _PROJECT_ROOT / "docs"
_STATIC_ROOT: Path = _DOCS_DIR / "assets"
_SPLIT_ADDRESS_DIR: Path = _PROJECT_ROOT / "split-address"


def _oku_display(raw: str | float | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return ""
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            return ""
    else:
        value = raw
    return f"{value / 100_000_000:,.2f}"


def _to_float_safe(raw: str | float | None) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw) if isinstance(raw, float) else float(raw)
    s = raw.strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def build_ranking_payload(input_dir: Path | None = None) -> list[dict]:
    """Build ranking JSON payload merging land value CSV data with screening metrics."""
    from formula_screening.web import compute_all_stock_metrics

    resolved_input_dir: Path = input_dir or DEFAULT_OUTPUT_DIR

    conn = connect_company_db()
    try:
        company_records = load_company_directory(conn)
        rank_rows = collect_rank_rows(resolved_input_dir, company_records)
    finally:
        conn.close()

    screening_metrics = compute_all_stock_metrics()

    payload: list[dict] = []
    for row in rank_rows:
        code = (row.get("証券コード") or "")
        if isinstance(code, str):
            code = code.strip()
        else:
            code = str(code).strip()

        ratio = _to_float_safe(row.get("時価総額比"))
        estimated_value = _to_float_safe(row.get("推定土地時価(円)"))
        market_cap = _to_float_safe(row.get("時価総額(円)"))
        book_value = _to_float_safe(row.get("土地簿価(円)"))
        unrealized_gain = _to_float_safe(row.get("含み益(円)"))

        memo_content = row.get("調査メモ", "")
        memo_html = _md_to_html(memo_content) if memo_content and isinstance(memo_content, str) else None

        metrics = screening_metrics.get(code, {})

        payload.append({
            "code": code,
            "name": (row.get("企業名") or "").strip(),
            "price": metrics.get("price"),
            "ratio": ratio,
            "estimated_value": estimated_value,
            "market_cap": market_cap,
            "book_value": book_value,
            "unrealized_gain": unrealized_gain,
            "geocode_tag": row.get("住所解決タグ", ""),
            "confidence": row.get("地価推定信頼度", ""),
            "anomaly": row.get("異常値警告", ""),
            "memo_html": memo_html,
            "metrics": {
                "net_cash_ratio": metrics.get("net_cash_ratio"),
                "per_actual": metrics.get("per_actual"),
                "per": metrics.get("per"),
                "per_next": metrics.get("per_next"),
                "equity_ratio": metrics.get("equity_ratio"),
                "fcf_yield_avg": metrics.get("fcf_yield_avg"),
                "croic": metrics.get("croic"),
                "peg_trailing_5": metrics.get("peg_trailing_5"),
                "peg_blended_5y_actual_2f": metrics.get("peg_blended_5y_actual_2f"),
            },
        })

    return payload


def serve_ranking(
    *,
    input_dir: Path | None = None,
    server_config: ServerConfig | None = None,
) -> None:
    """Start the web UI server with ranking data."""
    payload = build_ranking_payload(input_dir)
    api_routes: dict[str, ApiHandler] = {
        "/api/ranking": json_route(lambda _params: payload),
    }

    _serve(
        static_root=_STATIC_ROOT,
        index_page=IndexPage(
            title="Land Value Ranking",
            loading_message="ランキングを読み込み中です。",
            tab_aria_label="タブ切替",
        ),
        server_config=server_config,
        api_routes=api_routes,
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="land-value-web",
        description="Web UI で時価総額比ランキングを表示する",
    )
    parser.add_argument("--input-dir", default=str(DEFAULT_OUTPUT_DIR), help="企業別CSVがあるフォルダ")
    args = parser.parse_args()
    serve_ranking(input_dir=Path(args.input_dir))


if __name__ == "__main__":
    main()
