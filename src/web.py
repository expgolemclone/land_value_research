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
from src.screening_config import load_screening_config

logger = logging.getLogger(__name__)

_PROJECT_ROOT: Path = PROJECT_ROOT
_DOCS_DIR: Path = _PROJECT_ROOT / "docs"
_STATIC_ROOT: Path = _DOCS_DIR / "assets"
_STOCK_PRICE_METADATA_PATH: Path = _STATIC_ROOT / "stock-price-meta.json"
_NET_CASH_FCF_SCREENING_CONFIG: Path = _PROJECT_ROOT / "config" / "screening" / "net_cash_fcf.toml"

StockPriceMetadata = dict[str, str | None]


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


def _codes_from_rank_rows(rank_rows: list[dict]) -> list[str]:
    codes: list[str] = []
    seen: set[str] = set()
    for row in rank_rows:
        code = str(row.get("code", "")).strip()
        if not code or code in seen:
            continue
        seen.add(code)
        codes.append(code)
    return codes


def _screening_payload_to_metric_map(payload: list[dict]) -> dict[str, dict]:
    metric_map: dict[str, dict] = {}
    for row in payload:
        code = str(row.get("code", "")).strip()
        if not code:
            continue

        nested_metrics = row.get("metrics")
        metrics = dict(nested_metrics) if isinstance(nested_metrics, dict) else {}
        for key in (
            "price",
            "fcf_yield_avg",
            "croic",
            "peg_trailing_5",
            "peg_trailing_5_status",
            "peg_blended_5y_actual_2f",
            "peg_blended_5y_actual_2f_status",
            "has_preferred_shares",
        ):
            metrics[key] = row.get(key)
        metric_map[code] = metrics
    return metric_map


def _load_screening_metrics(
    rank_rows: list[dict],
    screening_config: Path | str | None,
) -> tuple[dict[str, dict], set[str] | None]:
    if screening_config is None:
        from formula_screening.web import compute_all_stock_metrics

        return compute_all_stock_metrics(), None

    config = load_screening_config(screening_config)
    candidate_codes = _codes_from_rank_rows(rank_rows)
    if not candidate_codes:
        return {}, set()

    from formula_screening.web import run_screening_strategy_payload

    screening_payload = run_screening_strategy_payload(
        config.strategy_path,
        tickers=candidate_codes,
    )
    metrics = _screening_payload_to_metric_map(screening_payload)
    return metrics, set(metrics)


def build_ranking_payload(
    input_dir: Path | str | None = None,
    screening_config: Path | str | None = None,
) -> list[dict]:
    """Build ranking JSON payload merging land value CSV data with Rust-backed screening metrics."""

    resolved_input_dir = Path(input_dir) if input_dir is not None else DEFAULT_OUTPUT_DIR

    conn = connect_company_db()
    try:
        company_records = load_company_directory(conn)
        rank_rows = collect_rank_rows(resolved_input_dir, company_records)
    finally:
        conn.close()

    if not rank_rows:
        return []

    screening_metrics, allowed_codes = _load_screening_metrics(rank_rows, screening_config)
    if allowed_codes is not None:
        rank_rows = [row for row in rank_rows if row["code"].strip() in allowed_codes]

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
            "fcf_yield_avg": metrics.get("fcf_yield_avg"),
            "croic": metrics.get("croic"),
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


def build_stock_price_metadata(db_path: Path | str | None = None) -> StockPriceMetadata:
    """Build latest stock price date metadata for the shared table status."""

    from formula_screening.web import build_stock_price_metadata as _build_stock_price_metadata

    return _build_stock_price_metadata(db_path)


def export_stock_price_metadata_json(
    output_path: Path | str = _STOCK_PRICE_METADATA_PATH,
    db_path: Path | str | None = None,
) -> Path:
    """Write latest stock price date metadata for static pages."""

    resolved_output_path = Path(output_path)
    metadata: StockPriceMetadata = build_stock_price_metadata(db_path)
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_output_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("stock price metadata JSON exported: %s", resolved_output_path)
    return resolved_output_path


def export_ranking_json(
    output_path: Path | str,
    input_dir: Path | str | None = None,
    screening_config: Path | str | None = None,
) -> None:
    """Write GitHub Pages compatible ranking payload JSON."""
    resolved_output_path = Path(output_path)
    payload = build_ranking_payload(input_dir, screening_config=screening_config)
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_output_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    logger.info("ranking JSON exported: %s (%d rows)", resolved_output_path, len(payload))


def export_github_pages_json(
    input_dir: Path | str | None = None,
    output_dir: Path | str | None = None,
    screening_config: Path | str | None = None,
) -> tuple[Path, Path]:
    """Write the standard and net_cash_fcf GitHub Pages ranking JSON files."""
    resolved_output_dir = Path(output_dir) if output_dir is not None else _STATIC_ROOT
    standard_path = resolved_output_dir / "ranking.json"
    screened_path = resolved_output_dir / "ranking_net_cash_fcf.json"
    resolved_screening_config = screening_config if screening_config is not None else _NET_CASH_FCF_SCREENING_CONFIG

    export_ranking_json(standard_path, input_dir=input_dir)
    export_ranking_json(
        screened_path,
        input_dir=input_dir,
        screening_config=resolved_screening_config,
    )
    export_stock_price_metadata_json(resolved_output_dir / "stock-price-meta.json")
    return standard_path, screened_path


def serve_ranking(
    *,
    input_dir: Path | str | None = None,
    screening_config: Path | str | None = None,
    server_config: ServerConfig | None = None,
) -> None:
    """Start the web UI server with ranking data."""
    payload = build_ranking_payload(input_dir, screening_config=screening_config)
    metadata: StockPriceMetadata = build_stock_price_metadata()
    api_routes: dict[str, ApiHandler] = {
        "/api/ranking": json_route(lambda _params: payload),
        "/api/stock-price-meta": json_route(lambda _params: metadata),
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
    parser.add_argument(
        "--export-github-pages",
        action="store_true",
        default=False,
        help="GitHub Pages用に通常版とnet_cash_fcf版のランキングJSONを書き出して終了する",
    )
    parser.add_argument(
        "--screening-config",
        type=Path,
        default=None,
        help="formula_screening のTOML戦略でランキングを絞り込む表示設定TOML",
    )
    args = parser.parse_args()
    if args.export_json is not None and args.export_github_pages:
        parser.error("--export-json and --export-github-pages cannot be used together")
    if args.export_github_pages:
        export_github_pages_json(
            input_dir=Path(args.input_dir),
            screening_config=args.screening_config,
        )
        return
    if args.export_json is not None:
        export_ranking_json(
            args.export_json,
            input_dir=Path(args.input_dir),
            screening_config=args.screening_config,
        )
        export_stock_price_metadata_json(args.export_json.parent / "stock-price-meta.json")
        return
    serve_ranking(input_dir=Path(args.input_dir), screening_config=args.screening_config)


if __name__ == "__main__":
    main()
