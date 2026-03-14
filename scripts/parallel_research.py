"""Cross-platform launcher for parallel address research.

Reads ranking_market_cap_ratio.html, filters target companies, and launches
parallel Claude Code CLI processes to run address research skills.

Usage:
    uv run python scripts/parallel_research.py split-address --n 3
    uv run python scripts/parallel_research.py resolve-address --n 2
    uv run python scripts/parallel_research.py split-address --n 3 --dry-run
"""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts._codex_check_tracker import get as get_check_count
from scripts._codex_check_tracker import increment as increment_check
from scripts._codex_precheck import precheck

RANKING_FILE = PROJECT_ROOT / "data" / "ranking" / "ranking_market_cap_ratio.html"
PATCH_DIR = PROJECT_ROOT / "config" / "address_patches"
LOG_DIR = PROJECT_ROOT / "data" / "output" / "research_logs"


# ---------------------------------------------------------------------------
# Ranking parser
# ---------------------------------------------------------------------------


def parse_ranking() -> list[dict[str, str]]:
    """Parse ranking HTML table into list of company dicts."""
    from html.parser import HTMLParser

    if not RANKING_FILE.exists():
        print(f"エラー: ランキングファイルが見つかりません: {RANKING_FILE}", file=sys.stderr)
        sys.exit(1)

    class _TableParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.rows: list[list[str]] = []
            self._in_td = False
            self._current_row: list[str] = []
            self._current_cell = ""
            self._in_tbody = False

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag == "tbody":
                self._in_tbody = True
            elif tag == "tr" and self._in_tbody:
                self._current_row = []
            elif tag == "td" and self._in_tbody:
                self._in_td = True
                self._current_cell = ""

        def handle_endtag(self, tag: str) -> None:
            if tag == "tbody":
                self._in_tbody = False
            elif tag == "td" and self._in_td:
                self._current_row.append(self._current_cell.strip())
                self._in_td = False
            elif tag == "tr" and self._in_tbody and self._current_row:
                self.rows.append(self._current_row)

        def handle_data(self, data: str) -> None:
            if self._in_td:
                self._current_cell += data

    parser = _TableParser()
    parser.feed(RANKING_FILE.read_text(encoding="utf-8"))

    targets: list[dict[str, str]] = []
    for cols in parser.rows:
        if len(cols) < 11:
            continue
        targets.append(
            {
                "rank": cols[0],
                "code": cols[1],
                "name": cols[2],
                "tag": cols[9],
            }
        )
    return targets


# ---------------------------------------------------------------------------
# split-address mode
# ---------------------------------------------------------------------------


def _run_precheck(selected: list[dict[str, str]]) -> dict[str, dict | None]:
    """Run precheck for each company (split-address mode)."""
    print("=== 事前検証 ===\n")
    results: dict[str, dict | None] = {}
    for t in selected:
        code = t["code"]
        print(f"  検証中: {code} {t['name']}...", end="", flush=True)
        try:
            result = precheck(code)
            results[code] = result
            if result.get("has_risk"):
                risk_count = sum(
                    1
                    for s in result["sites"]
                    if s.get("bad_pattern_1_risk") or s.get("geocode_level") != "gaiku" or s.get("has_multi_loc_warning")
                )
                print(f" リスクあり ({risk_count}拠点)")
            else:
                print(" リスクなし (全gaiku)")
        except Exception as e:
            print(f" エラー: {e}")
            results[code] = None
    print()
    return results


def _codex_check_filter(selected: list[dict[str, str]]) -> list[dict[str, str]]:
    """Filter out companies that have reached CODEX_CHECK limit (>=2)."""
    filtered: list[dict[str, str]] = []
    for t in selected:
        count = get_check_count(t["code"])
        if count >= 2:
            print(f"  スキップ: {t['code']} {t['name']} (CODEX_CHECK_{count}, 調査上限)")
        else:
            filtered.append(t)
    return filtered


def _print_precheck_details(selected: list[dict[str, str]], precheck_results: dict[str, dict | None]) -> None:
    """Print detailed precheck results for dry-run."""
    print("(DryRun: 事前検証結果の詳細)\n")
    for t in selected:
        code = t["code"]
        result = precheck_results.get(code)
        if result is None:
            print(f"  {code}: (検証失敗)")
            continue
        print(f"  {code} {t['name']}:")
        print(f"    all_gaiku={result['all_gaiku']}  has_risk={result['has_risk']}")
        for site in result.get("sites", []):
            flags: list[str] = []
            if site.get("bad_pattern_1_risk"):
                flags.append("BAD1")
            if site.get("has_hoka"):
                flags.append("hoka")
            if site.get("geocode_level") != "gaiku":
                flags.append(site.get("geocode_level", "?"))
            if site.get("has_override"):
                flags.append("override")
            flag_str = f" [{','.join(flags)}]" if flags else ""
            print(f"    {site['site_name']}  area={site['area_m2']}  geocode={site['geocode_level']}{flag_str}")
        print()
    print("(DryRun: ここで終了)")


def run_split_address(args: argparse.Namespace) -> None:
    targets = parse_ranking()
    if not targets:
        print("ランキングに企業が見つかりませんでした.")
        return

    selected = targets[: args.n]

    print("\n=== 並行 split-address ===\n")
    _print_targets(selected)

    precheck_results = _run_precheck(selected)

    # CODEX_CHECK filter
    selected = _codex_check_filter(selected)
    if not selected:
        print("全企業が CODEX_CHECK 上限に達しています.")
        return
    print(f"CODEX_CHECK フィルタ後: {len(selected)} 件\n")

    if args.dry_run:
        _print_precheck_details(selected, precheck_results)
        return

    # Increment counters
    for t in selected:
        increment_check(t["code"])

    _prepare_patch_dir()

    # Write precheck JSON files
    for t in selected:
        code = t["code"]
        result = precheck_results.get(code)
        if result is not None:
            pcheck_file = PATCH_DIR / f"{code}.precheck.json"
            pcheck_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # Build prompts
    prompts = {
        t["code"]: f"/split-address {t['code']} の時価総額比の土地の含み益が高すぎておかしいだろ?. 分割できないか調査しろ."
        for t in selected
    }
    _launch_processes(selected, prompts, args.cli)


# ---------------------------------------------------------------------------
# resolve-address mode
# ---------------------------------------------------------------------------


def run_resolve_address(args: argparse.Namespace) -> None:
    targets = parse_ranking()
    filtered = [t for t in targets if re.search(r"muni_centroid|oaza_chome", t["tag"])]
    if not filtered:
        print("低解像度企業は見つかりませんでした.")
        return

    selected = filtered[: args.n]

    print("\n=== 並行 resolve-address ===\n")
    _print_targets(selected)

    if args.dry_run:
        print("(DryRun: ここで終了)")
        return

    _prepare_patch_dir()

    prompts = {t["code"]: f"/resolve-address {t['code']} config/address_patches/{t['code']}.yaml" for t in selected}
    _launch_processes(selected, prompts, args.cli)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _print_targets(selected: list[dict[str, str]]) -> None:
    print(f"対象企業 ({len(selected)}件):")
    for t in selected:
        print(f"  {t['rank']:>4}位: {t['code']} {t['name']}\t[{t['tag']}]")
    print()


def _prepare_patch_dir() -> None:
    """Clean YAML files in patch dir or create it."""
    if PATCH_DIR.exists():
        for f in PATCH_DIR.glob("*.yaml"):
            f.unlink()
    else:
        PATCH_DIR.mkdir(parents=True)
    print(f"パッチディレクトリ: {PATCH_DIR} (クリア済み)\n")


def _launch_processes(
    selected: list[dict[str, str]],
    prompts: dict[str, str],
    cli_cmd: str,
) -> None:
    """Launch parallel CLI processes and wait for completion."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"{len(selected)} プロセスを起動します...\n")

    running: list[dict] = []
    for i, t in enumerate(selected):
        code = t["code"]
        prompt = prompts[code]
        log_file = LOG_DIR / f"{timestamp}_{code}.log"

        cmd = [cli_cmd, "-p", prompt]
        print(f"  [{i + 1}] {code} {t['name']}")
        print(f"      log: {log_file}")

        fh = open(log_file, "w", encoding="utf-8")  # noqa: SIM115
        proc = subprocess.Popen(
            cmd,
            cwd=PROJECT_ROOT,
            stdout=fh,
            stderr=subprocess.STDOUT,
            env={**os.environ, "NO_COLOR": "1"},
        )
        running.append({"proc": proc, "code": code, "name": t["name"], "fh": fh, "log": log_file})

    print("\n全プロセス起動完了. 完了を待機中...\n")

    for p in running:
        p["proc"].wait()
        p["fh"].close()
        rc = p["proc"].returncode
        status = "完了" if rc == 0 else f"エラー (code={rc})"
        print(f"  {p['code']} {p['name']}: {status}")

    print("\n=== 全プロセス完了 ===\n")
    print("次の手順:")
    print(f"  1. ログ確認:    ls {LOG_DIR}/{timestamp}_*.log")
    print(f"  2. パッチ確認:  ls {PATCH_DIR}/")
    print("  3. マージ:      uv run python scripts/merge_address_patches.py")
    print("  4. 再実行:      uv run python run.py")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="並行住所調査ランチャー (split-address / resolve-address)",
    )
    parser.add_argument(
        "mode",
        choices=["split-address", "resolve-address"],
        help="調査モード",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=1,
        help="同時起動プロセス数 (default: 1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="対象一覧を表示するだけで起動しない",
    )
    parser.add_argument(
        "--cli",
        default="claude",
        help="CLI コマンド (default: claude)",
    )

    args = parser.parse_args(argv)

    if args.mode == "split-address":
        run_split_address(args)
    else:
        run_resolve_address(args)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
