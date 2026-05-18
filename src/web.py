"""Web UI integration: serves land value ranking via stock_web_ui."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from stock_web_ui.config import ServerConfig
from stock_web_ui.handler import ApiHandler, json_route
from stock_web_ui.page import IndexPage
from stock_web_ui.serve import serve as _serve

from src.company_store import connect_company_db, load_company_directory
from src.config import DEFAULT_OUTPUT_DIR, PROJECT_ROOT
from src.ranking_data import collect_rank_rows, markdown_to_html

logger = logging.getLogger(__name__)

_PROJECT_ROOT: Path = PROJECT_ROOT
_DOCS_DIR: Path = _PROJECT_ROOT / "docs"
_STATIC_ROOT: Path = _DOCS_DIR / "assets"
_STOCK_PRICE_META_JSON: Path = _STATIC_ROOT / "stock-price-meta.json"


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
        logger.debug("float conversion failed: %r", s)
        return None


def build_ranking_payload(input_dir: Path | str | None = None) -> list[dict]:
    """Build ranking JSON payload merging land value CSV data with Rust-backed screening metrics."""
    from formula_screening.web import compute_all_stock_metrics

    resolved_input_dir = Path(input_dir) if input_dir is not None else DEFAULT_OUTPUT_DIR

    conn = connect_company_db()
    try:
        company_records = load_company_directory(conn)
        rank_rows = collect_rank_rows(resolved_input_dir, company_records)
    finally:
        conn.close()

    screening_metrics = compute_all_stock_metrics()

    payload: list[dict] = []
    for row in rank_rows:
        code = row["code"].strip()

        ratio = _to_float_safe(row.get("ratio"))
        estimated_value = _to_float_safe(row.get("estimated_value"))
        market_cap = _to_float_safe(row.get("market_cap"))
        book_value = _to_float_safe(row.get("book_value"))
        unrealized_gain = _to_float_safe(row.get("unrealized_gain"))

        memo_content = row.get("memo_markdown", "")
        memo_html = markdown_to_html(memo_content) if memo_content else None

        metrics = screening_metrics.get(code, {})

        payload.append({
            "code": code,
            "name": row["name"].strip(),
            "price": metrics.get("price"),
            "peg_trailing_5": metrics.get("peg_trailing_5"),
            "peg_trailing_5_status": metrics.get("peg_trailing_5_status"),
            "peg_blended_5y_actual_2f": metrics.get("peg_blended_5y_actual_2f"),
            "peg_blended_5y_actual_2f_status": metrics.get("peg_blended_5y_actual_2f_status"),
            "ratio": ratio,
            "estimated_value": estimated_value,
            "market_cap": market_cap,
            "book_value": book_value,
            "unrealized_gain": unrealized_gain,
            "geocode_tag": row.get("geocode_tag", ""),
            "confidence": row.get("confidence", ""),
            "anomaly": row.get("anomaly", ""),
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
                "peg_trailing_5_status": metrics.get("peg_trailing_5_status"),
                "peg_blended_5y_actual_2f": metrics.get("peg_blended_5y_actual_2f"),
                "peg_blended_5y_actual_2f_status": metrics.get("peg_blended_5y_actual_2f_status"),
                "has_preferred_shares": metrics.get("has_preferred_shares"),
            },
        })

    return payload


def build_stock_price_metadata(db_path: Path | str | None = None) -> dict[str, str | None]:
    from stock_db.paths import STOCKS_DB_PATH
    from stock_db.storage.connection import get_connection
    from stock_db.storage.prices import get_latest_price_date

    resolved_db_path = Path(db_path) if db_path is not None else STOCKS_DB_PATH
    conn = get_connection(resolved_db_path)
    try:
        latest_price_date = get_latest_price_date(conn)
    finally:
        conn.close()
    return {"price_date": latest_price_date.isoformat() if latest_price_date else None}


def export_stock_price_metadata_json(
    output_path: Path | str = _STOCK_PRICE_META_JSON,
    *,
    db_path: Path | str | None = None,
) -> None:
    resolved_output_path = Path(output_path)
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_output_path.write_text(
        json.dumps(build_stock_price_metadata(db_path), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def export_ranking_json(output_path: Path | str, input_dir: Path | str | None = None) -> None:
    """Write GitHub Pages compatible ranking payload JSON."""
    resolved_output_path = Path(output_path)
    payload = build_ranking_payload(input_dir)
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_output_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    export_stock_price_metadata_json(resolved_output_path.with_name("stock-price-meta.json"))
    logger.info("ranking JSON exported: %s (%d rows)", resolved_output_path, len(payload))


def serve_ranking(
    *,
    input_dir: Path | str | None = None,
    server_config: ServerConfig | None = None,
) -> None:
    """Start the web UI server with ranking data."""
    payload = build_ranking_payload(input_dir)
    stock_price_metadata = build_stock_price_metadata()
    api_routes: dict[str, ApiHandler] = {
        "/api/ranking": json_route(lambda _params: payload),
        "/api/stock-price-meta": json_route(lambda _params: stock_price_metadata),
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
    parser.add_argument(
        "--export-json",
        type=Path,
        default=None,
        help="Web UI用ランキングJSONを書き出して終了する",
    )
    args = parser.parse_args()
    if args.export_json is not None:
        export_ranking_json(args.export_json, input_dir=Path(args.input_dir))
        return
    serve_ranking(input_dir=Path(args.input_dir))


if __name__ == "__main__":
    main()
