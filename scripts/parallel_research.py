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

from scripts._codex_precheck import precheck
from scripts.codex_lockdown import codex_lockdown

RANKING_FILE = PROJECT_ROOT / "data" / "ranking" / "ranking_market_cap_ratio.html"
PATCH_DIR = PROJECT_ROOT / "config" / "address_patches"
LOG_DIR = PROJECT_ROOT / "docs" / "research_logs"


# ---------------------------------------------------------------------------
# Ranking parser
# ---------------------------------------------------------------------------


def parse_ranking() -> list[dict[str, str]]:
    """Parse ranking HTML table into list of company dicts.

    Reads <th> headers first, then maps each <td> row by header name
    instead of relying on fragile column indices.
    """
    from html.parser import HTMLParser

    from src.schema import RANKING_COLUMNS

    if not RANKING_FILE.exists():
        print(f"エラー: ランキングファイルが見つかりません: {RANKING_FILE}", file=sys.stderr)
        sys.exit(1)

    class _TableParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.headers: list[str] = []
            self.rows: list[list[str]] = []
            self._in_th = False
            self._in_td = False
            self._current_row: list[str] = []
            self._current_cell = ""
            self._in_thead = False
            self._in_tbody = False

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag == "thead":
                self._in_thead = True
            elif tag == "tbody":
                self._in_tbody = True
            elif tag == "th" and self._in_thead:
                self._in_th = True
                self._current_cell = ""
            elif tag == "tr" and self._in_tbody:
                self._current_row = []
            elif tag == "td" and self._in_tbody:
                self._in_td = True
                self._current_cell = ""

        def handle_endtag(self, tag: str) -> None:
            if tag == "thead":
                self._in_thead = False
            elif tag == "tbody":
                self._in_tbody = False
            elif tag == "th" and self._in_th:
                self.headers.append(self._current_cell.strip())
                self._in_th = False
            elif tag == "td" and self._in_td:
                self._current_row.append(self._current_cell.strip())
                self._in_td = False
            elif tag == "tr" and self._in_tbody and self._current_row:
                self.rows.append(self._current_row)

        def handle_data(self, data: str) -> None:
            if self._in_th:
                self._current_cell += data
            elif self._in_td:
                self._current_cell += data

    parser = _TableParser()
    parser.feed(RANKING_FILE.read_text(encoding="utf-8"))

    # Validate headers against schema
    if tuple(parser.headers) != RANKING_COLUMNS:
        print(
            f"エラー: ランキングHTMLのヘッダーがスキーマと不一致\n"
            f"  期待: {list(RANKING_COLUMNS)}\n"
            f"  実際: {parser.headers}",
            file=sys.stderr,
        )
        sys.exit(1)

    targets: list[dict[str, str]] = []
    for cols in parser.rows:
        if len(cols) != len(parser.headers):
            continue
        row = dict(zip(parser.headers, cols))
        targets.append(
            {
                "rank": row["順位"],
                "code": row["証券コード"],
                "name": row["企業名"],
                "tag": row["住所解決タグ"],
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
    """Filter out companies whose docs/{code}.md already exists."""
    filtered: list[dict[str, str]] = []
    for t in selected:
        docs_md = PROJECT_ROOT / "docs" / f"{t['code']}.md"
        if docs_md.exists():
            print(f"  スキップ: {t['code']} {t['name']} (調査済み: docs/{t['code']}.md)")
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

    # docs/{code}.md 存在チェック (調査済み企業を除外)
    targets = _codex_check_filter(targets)
    if not targets:
        print("全企業が調査済みです (docs/*.md が存在).")
        return

    selected = targets[: args.n]

    print("\n=== 並行 split-address ===\n")
    _print_targets(selected)

    precheck_results = _run_precheck(selected)

    if args.dry_run:
        _print_precheck_details(selected, precheck_results)
        return

    _prepare_patch_dir()

    # Write precheck JSON files
    for t in selected:
        code = t["code"]
        result = precheck_results.get(code)
        if result is not None:
            pcheck_file = PATCH_DIR / f"{code}.precheck.json"
            pcheck_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # Ensure docs/{code}.md exists before lockdown (docs/ will be 0o111)
    docs_dir = PROJECT_ROOT / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    for t in selected:
        docs_md = docs_dir / f"{t['code']}.md"
        if not docs_md.exists():
            docs_md.touch()

    # Ensure log dir exists before lockdown (docs/ will be 0o111)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Build prompts
    prompts = {
        t["code"]: _build_injected_prompt(
            code=t["code"],
            mode="split-address",
            cli=args.cli,
            user_instruction=f"{t['code']} の時価総額比の土地の含み益が高すぎておかしいだろ?. 分割できないか調査しろ.",
        )
        for t in selected
    }
    codes = [t["code"] for t in selected]
    with codex_lockdown(target_codes=codes, mode="split-address"):
        _launch_processes(selected, prompts, args.cli, check_docs=True)


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

    # Ensure log dir exists before lockdown (docs/ will be 0o111)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    prompts = {
        t["code"]: _build_injected_prompt(
            code=t["code"],
            mode="resolve-address",
            cli=args.cli,
            user_instruction=f"{t['code']} config/address_patches/{t['code']}.yaml",
        )
        for t in selected
    }
    codes = [t["code"] for t in selected]
    with codex_lockdown(target_codes=codes, mode="resolve-address"):
        _launch_processes(selected, prompts, args.cli)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _build_injected_prompt(
    code: str,
    mode: str,
    cli: str,
    user_instruction: str,
) -> str:
    """SKILL.md + 参照ファイルを結合したプロンプトを構築."""
    if cli == "codex":
        skill_dir = PROJECT_ROOT / ".agents" / "skills" / mode
    else:
        skill_dir = PROJECT_ROOT / ".claude" / "skills" / mode

    skill_content = (skill_dir / "SKILL.md").read_text(encoding="utf-8")

    parts: list[str] = []

    # SKILL.md 注入
    parts.append(f"<skill>\n{skill_content}\n</skill>")

    # precheck JSON 注入 (split-address のみ)
    if mode == "split-address":
        pcheck = PATCH_DIR / f"{code}.precheck.json"
        if pcheck.exists():
            pcheck_content = pcheck.read_text(encoding="utf-8")
            parts.append(
                f'<context path="config/address_patches/{code}.precheck.json">\n{pcheck_content}\n</context>'
            )

    # facilities_land (有報 設備の状況) 注入 — 両モード共通
    sites_path = PROJECT_ROOT / "data" / "cache" / "facilities_land" / f"{code}_sites.json"
    if sites_path.exists():
        sites_content = sites_path.read_text(encoding="utf-8")
        parts.append(
            f'<context path="data/cache/facilities_land/{code}_sites.json">\n{sites_content}\n</context>'
        )

    # output CSV 注入
    csv_path = PROJECT_ROOT / "data" / "output" / f"{code}_output.csv"
    if csv_path.exists():
        csv_content = csv_path.read_text(encoding="utf-8")
        parts.append(
            f'<context path="data/output/{code}_output.csv">\n{csv_content}\n</context>'
        )

    # ユーザー指示
    parts.append(user_instruction)

    return "\n\n".join(parts)


def _print_targets(selected: list[dict[str, str]]) -> None:
    print(f"対象企業 ({len(selected)}件):")
    for t in selected:
        print(f"  {t['rank']:>4}位: {t['code']} {t['name']}\t[{t['tag']}]")
    print()


def _prepare_patch_dir() -> None:
    """Clean patch dir (YAML + precheck JSON) or create it."""
    if PATCH_DIR.exists():
        for f in PATCH_DIR.glob("*.yaml"):
            f.unlink()
        for f in PATCH_DIR.glob("*.precheck.json"):
            f.unlink()
    else:
        PATCH_DIR.mkdir(parents=True)
    print(f"パッチディレクトリ: {PATCH_DIR} (クリア済み)\n")


def _launch_processes(
    selected: list[dict[str, str]],
    prompts: dict[str, str],
    cli_cmd: str,
    *,
    check_docs: bool = False,
) -> None:
    """Launch parallel CLI processes in new kitty windows."""
    import shlex

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"{len(selected)} プロセスを kitty ウィンドウで起動します...\n")

    running: list[dict] = []
    for i, t in enumerate(selected):
        code = t["code"]
        prompt = prompts[code]
        log_file = LOG_DIR / f"{timestamp}_{code}.log"

        # プロンプトをファイル経由で渡す (シェルエスケープ問題を回避)
        prompt_file = LOG_DIR / f"{timestamp}_{code}.prompt.txt"
        prompt_file.write_text(prompt, encoding="utf-8")

        title = f"{code} {t['name']}"
        shell_cmd = (
            f"{cli_cmd} exec --full-auto \"$(<{shlex.quote(str(prompt_file))})\" "
            f"2>&1 | tee {shlex.quote(str(log_file))};"
            f' echo "\\n--- 完了 (Enter で閉じる) ---"; read'
        )
        cmd = ["kitty", "--title", title, "-e", "bash", "-c", shell_cmd]

        print(f"  [{i + 1}] {title}")
        print(f"      log: {log_file}")

        proc = subprocess.Popen(
            cmd,
            cwd=PROJECT_ROOT,
            env={**os.environ, "NO_COLOR": "1"},
        )
        running.append({"proc": proc, "code": code, "name": t["name"], "log": log_file})

    print("\n全プロセス起動完了. 完了を待機中...\n")

    for p in running:
        p["proc"].wait()
        rc = p["proc"].returncode
        status = "完了" if rc == 0 else f"エラー (code={rc})"
        print(f"  {p['code']} {p['name']}: {status}")
        if p["log"].exists() and p["log"].stat().st_size == 0:
            print(f"  {p['code']} {p['name']}: 警告 - ログが空です")
        if check_docs:
            docs_md = PROJECT_ROOT / "docs" / f"{p['code']}.md"
            if not docs_md.exists():
                print(f"  {p['code']} {p['name']}: エラー - docs/{p['code']}.md が存在しません")
            elif docs_md.stat().st_size == 0:
                print(f"  {p['code']} {p['name']}: エラー - docs/{p['code']}.md が空です (推論メモ未保存)")

    print("\n=== 全プロセス完了 ===\n")
    print("次の手順:")
    print(f"  1. ログ確認:    ls {LOG_DIR}/{timestamp}_*.log")
    print(f"  2. パッチ確認:  ls {PATCH_DIR}/")
    print("  3. マージ:      uv run python scripts/merge_address_patches.py")
    print("  4. 再実行:      uv run python run.py")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _ensure_nix_devshell() -> None:
    """nix develop 外なら自動で re-exec する."""
    import shutil

    if shutil.which("rustc"):
        return
    if os.environ.get("_IN_NIX_DEVELOP"):
        print("エラー: nix develop 内でも rustc が見つかりません", file=sys.stderr)
        sys.exit(1)
    print("[parallel_research] rustc not found, re-launching via nix develop...")
    nix = shutil.which("nix")
    if not nix:
        print("エラー: nix が見つかりません", file=sys.stderr)
        sys.exit(1)
    env = {**os.environ, "_IN_NIX_DEVELOP": "1"}
    os.execve(
        nix,
        ["nix", "develop", "--command", sys.executable, *sys.argv],
        env,
    )


def main(argv: list[str] | None = None) -> int:
    _ensure_nix_devshell()
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
        default="codex",
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
