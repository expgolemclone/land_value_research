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
from src.paths import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_RANKING_PATH,
    FACILITIES_CACHE_DIR,
)
from src.paths import PATCH_DIR as _PATCH_DIR

RANKING_FILE = DEFAULT_RANKING_PATH
PATCH_DIR = _PATCH_DIR
LOG_DIR = PROJECT_ROOT / "split-address" / "research_logs"


# ---------------------------------------------------------------------------
# Ranking parser
# ---------------------------------------------------------------------------


def parse_ranking() -> list[dict[str, str]]:
    """Parse ranking HTML table into list of company dicts.

    Reads <th> headers first, then maps each <td> row by header name
    instead of relying on fragile column indices.
    """
    from html.parser import HTMLParser

    from src.schema import COL_CODE, COL_COMPANY_NAME, RANK_COL_GEOCODE_TAG, RANK_COL_RANK, RANKING_COLUMNS

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
            self._table_depth = 0

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag == "table":
                self._table_depth += 1
                return
            if self._table_depth != 1:
                return
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
            if tag == "table":
                self._table_depth -= 1
                return
            if self._table_depth != 1:
                return
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
            if self._table_depth != 1:
                return
            if self._in_th:
                self._current_cell += data
            elif self._in_td:
                self._current_cell += data

    parser = _TableParser()
    parser.feed(RANKING_FILE.read_text(encoding="utf-8"))

    # Validate headers against schema (先頭列のみ — HTML末尾に調査メモ等の追加列がある)
    n = len(RANKING_COLUMNS)
    if tuple(parser.headers[:n]) != RANKING_COLUMNS:
        print(
            f"エラー: ランキングHTMLのヘッダーがスキーマと不一致\n"
            f"  期待: {list(RANKING_COLUMNS)}\n"
            f"  実際(先頭{n}列): {parser.headers[:n]}",
            file=sys.stderr,
        )
        sys.exit(1)

    targets: list[dict[str, str]] = []
    for cols in parser.rows:
        if len(cols) < n:
            continue
        row = dict(zip(RANKING_COLUMNS, cols[:n]))
        targets.append(
            {
                "rank": row[RANK_COL_RANK],
                "code": row[COL_CODE],
                "name": row[COL_COMPANY_NAME],
                "tag": row[RANK_COL_GEOCODE_TAG],
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
                    if s.get("bad_pattern_1_risk")
                    or s.get("geocode_level") != "gaiku"
                    or s.get("has_multi_loc_warning")
                )
                print(f" リスクあり ({risk_count}拠点)")
            else:
                print(" リスクなし (全gaiku)")
        except Exception as e:
            print(f" エラー: {e}")
            results[code] = None
    print()
    return results


def _cleanup_empty_docs() -> None:
    """Delete empty .md files in split-address/ left over from previous failed runs."""
    docs_dir = PROJECT_ROOT / "split-address"
    if not docs_dir.is_dir():
        return
    for md in docs_dir.glob("*.md"):
        if md.stat().st_size == 0:
            print(f"  空ファイル削除: split-address/{md.name}")
            md.unlink()


def _codex_check_filter(selected: list[dict[str, str]]) -> list[dict[str, str]]:
    """Filter out companies whose split-address/{code}.md already exists."""
    filtered: list[dict[str, str]] = []
    for t in selected:
        docs_md = PROJECT_ROOT / "split-address" / f"{t['code']}.md"
        if docs_md.exists():
            print(f"  スキップ: {t['code']} {t['name']} (調査済み: split-address/{t['code']}.md)")
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

    # 前回失敗時の空ファイルを掃除してから絞り込む
    _cleanup_empty_docs()

    # split-address/{code}.md 存在チェック (調査済み企業を除外)
    targets = _codex_check_filter(targets)
    if not targets:
        print("全企業が調査済みです (split-address/*.md が存在).")
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

    # Ensure split-address/{code}.md exists before lockdown (split-address/ will be 0o111)
    docs_dir = PROJECT_ROOT / "split-address"
    docs_dir.mkdir(parents=True, exist_ok=True)
    for t in selected:
        docs_md = docs_dir / f"{t['code']}.md"
        if not docs_md.exists():
            docs_md.touch()

    # Ensure log dir exists before lockdown (split-address/ will be 0o111)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Build prompts
    prompts = {
        t["code"]: _build_injected_prompt(
            code=t["code"],
            mode="split-address",
            cli=args.cli,
            user_instruction=(
                f"{t['code']} の時価総額比の土地の含み益が高すぎておかしいだろ?. "
                "分割できないか調査しろ. "
                "テナントを自社保有かのように書いている悪い会社もあるので注意."
            ),
        )
        for t in selected
    }
    codes = [t["code"] for t in selected]
    with codex_lockdown(target_codes=codes, mode="split-address"):
        timestamp = _launch_processes(selected, prompts, args.cli, check_docs=True, check_patch=True)
    _post_process(timestamp, selected)


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

    # Ensure log dir exists before lockdown (split-address/ will be 0o111)
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
        timestamp = _launch_processes(selected, prompts, args.cli)
    _post_process(timestamp, selected)


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
            parts.append(f'<context path="config/address_patches/{code}.precheck.json">\n{pcheck_content}\n</context>')

    # facilities_land (有報 設備の状況) 注入 — 両モード共通
    sites_path = FACILITIES_CACHE_DIR / f"{code}_sites.json"
    if sites_path.exists():
        sites_content = sites_path.read_text(encoding="utf-8")
        parts.append(f'<context path="data/cache/facilities_land/{code}_sites.json">\n{sites_content}\n</context>')

    # facilities_text (有報 設備の状況 ページテキスト) 注入
    text_path = FACILITIES_CACHE_DIR / f"{code}_facilities_text.txt"
    if text_path.exists():
        text_content = text_path.read_text(encoding="utf-8")
        parts.append(
            f'<context path="data/cache/facilities_land/{code}_facilities_text.txt" '
            'description="有報「設備の状況」セクション全文（注記含む）">\n'
            f"{text_content}\n"
            "</context>"
        )

    # output CSV 注入
    csv_path = DEFAULT_OUTPUT_DIR / f"{code}_output.csv"
    if csv_path.exists():
        csv_content = csv_path.read_text(encoding="utf-8")
        parts.append(f'<context path="data/output/{code}_output.csv">\n{csv_content}\n</context>')

    # doubtful.md (信頼性チェックリスト) 注入 — split-address のみ
    if mode == "split-address":
        doubtful_path = PROJECT_ROOT / "split-address" / "doubtful.md"
        if doubtful_path.exists():
            doubtful_content = doubtful_path.read_text(encoding="utf-8")
            parts.append(
                f'<context path="split-address/doubtful.md" '
                'description="過去の調査で発見された問題パターン集。同様のパターンに該当しないか最終確認に使用せよ">\n'
                f"{doubtful_content}\n"
                "</context>"
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
    """Clean patch dir (YAML + precheck JSON) or create it.

    未マージのパッチが残っている場合は先にマージする。
    """
    if PATCH_DIR.exists():
        # 未マージパッチがあれば先にマージ
        leftover_patches = list(PATCH_DIR.glob("*.yaml"))
        if leftover_patches:
            print(f"未マージパッチ検出 ({len(leftover_patches)}件). 先にマージします...\n")
            subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "scripts" / "merge_address_patches.py")],
                cwd=PROJECT_ROOT,
            )
            print()
        # マージ後に残った YAML (マージ失敗分) と precheck を削除
        for f in PATCH_DIR.glob("*.yaml"):
            f.unlink()
        for f in PATCH_DIR.glob("*.precheck.json"):
            f.unlink()
    else:
        PATCH_DIR.mkdir(parents=True)
    print(f"パッチディレクトリ: {PATCH_DIR} (クリア済み)\n")


def _build_ps1_script(
    cli_cmd: str,
    prompt_file: Path,
    log_file: Path,
    *,
    cwd: Path | None = None,
    docs_path: Path | None = None,
    docs_label: str = "",
    patch_path: Path | None = None,
    patch_label: str = "",
) -> str:
    """PowerShell (.ps1) スクリプトを生成."""
    is_claude = cli_cmd == "claude"
    pf = str(prompt_file).replace("'", "''")
    lf = str(log_file).replace("'", "''")
    docs_retry_message = f"{docs_label} が空のままです。調査結果を書き込んでください。"
    patch_retry_message = (
        f"{patch_label} が作成されていません。"
        "住所の分割・修正が必要な場合はパッチファイルを作成してください。"
        f"現在の住所が正しい等の正当な理由がある場合は、その旨を {docs_label} に記載してください。"
    )
    lines: list[str] = [
        "[Console]::InputEncoding = [System.Text.Encoding]::UTF8",
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8",
        "$OutputEncoding = [System.Text.Encoding]::UTF8",
    ]
    if cwd is not None:
        lines.append(f"Set-Location -Path '{str(cwd).replace(chr(39), chr(39) * 2)}'")
    lines += [
        "$ErrorActionPreference = 'Continue'",
        f"$prompt = Get-Content -Path '{pf}' -Raw -Encoding UTF8",
    ]
    if is_claude:
        # claude -p は位置引数だとハングするため stdin 経由で渡す
        lines.append(
            f"Get-Content -Path '{pf}' -Raw -Encoding UTF8 "
            f"| & {cli_cmd} -p --dangerously-skip-permissions 2>&1 "
            f"| Tee-Object -FilePath '{lf}'"
        )
    else:
        lines.append(f"& {cli_cmd} exec --full-auto $prompt 2>&1 | Tee-Object -FilePath '{lf}'")
    if docs_path is not None:
        dp = str(docs_path).replace("'", "''")
        lines += [
            f"if (-not (Test-Path '{dp}') -or (Get-Item '{dp}').Length -eq 0) {{",
            f"  $m = Select-String -Path '{lf}' -Pattern 'session id: ' | Select-Object -First 1",
            "  $sid = ($m.Line -split 'session id: ')[1].Split()[0]",
            f'  Write-Host "`n--- {docs_label} が空. resume リトライ (SID=$sid) ---"',
        ]
        if is_claude:
            lines.append(
                f"  '{docs_retry_message}' "
                f"| & {cli_cmd} -r $sid -p --dangerously-skip-permissions 2>&1 "
                f"| Tee-Object -FilePath '{lf}' -Append"
            )
        else:
            lines.append(
                f"  & {cli_cmd} exec resume $sid --full-auto '{docs_retry_message}' 2>&1 "
                f"| Tee-Object -FilePath '{lf}' -Append"
            )
        lines.append("}")
    if patch_path is not None:
        pp = str(patch_path).replace("'", "''")
        lines += [
            f"if (-not (Test-Path '{pp}') -or (Get-Item '{pp}').Length -eq 0) {{",
            f"  $m = Select-String -Path '{lf}' -Pattern 'session id: ' | Select-Object -First 1",
            "  $sid = ($m.Line -split 'session id: ')[1].Split()[0]",
            '  Write-Host "`n--- パッチ未作成. コンテキスト注入 (SID=$sid) ---"',
        ]
        if is_claude:
            lines.append(
                f"  '{patch_retry_message}' "
                f"| & {cli_cmd} -r $sid -p --dangerously-skip-permissions 2>&1 "
                f"| Tee-Object -FilePath '{lf}' -Append"
            )
        else:
            lines.append(
                f"  & {cli_cmd} exec resume $sid --full-auto '{patch_retry_message}' 2>&1 "
                f"| Tee-Object -FilePath '{lf}' -Append"
            )
        lines.append("}")
    if docs_path is not None or patch_path is not None:
        lines.append('Write-Host "`n--- 完了 ---"')
    return "\n".join(lines) + "\n"


def _build_bash_script(
    cli_cmd: str,
    prompt_file: Path,
    log_file: Path,
    *,
    cwd: Path | None = None,
    docs_path: Path | None = None,
    docs_label: str = "",
    patch_path: Path | None = None,
    patch_label: str = "",
    _q: object = None,
) -> str:
    """bash (.sh) スクリプトを生成."""
    import shlex

    if _q is None:

        def _q(p: Path | str) -> str:
            return shlex.quote(str(p).replace("\\", "/"))

    log_q = _q(log_file)
    prompt_q = _q(prompt_file)
    is_claude = cli_cmd == "claude"
    shell_cmd = ""
    if cwd is not None:
        shell_cmd += f"cd {_q(cwd)} || exit 1; "
    if is_claude:
        # claude -p は位置引数だとハングするため stdin 経由で渡す
        import shlex as _shlex

        _sys_prompt = (
            "重要: 1) 必ずWebSearch/WebFetchで住所を調査すること"
            " 2) 必ずBashでジオコード検証(TokyoGeocoder)を実行すること"
            " 3) 必ずsplit-address/CODE.mdに推論メモを書くこと"
            " 4) git commit/pushは絶対に実行しないこと"
        )
        shell_cmd += (
            f"{cli_cmd} -p --dangerously-skip-permissions"
            f" --disallowedTools {_shlex.quote('Bash(git:*)')}"
            f" --effort max"
            f" --append-system-prompt {_shlex.quote(_sys_prompt)}"
            f" < {prompt_q} 2>&1 | tee {log_q}; "
        )
    else:
        shell_cmd += f'{cli_cmd} exec --full-auto "$(<{prompt_q})" 2>&1 | tee {log_q}; '
    if docs_path is not None:
        if is_claude:
            shell_cmd += (
                f"if [ ! -s {_q(docs_path)} ]; then "
                f"  SID=$(grep -m1 'session id: ' {log_q} | sed 's/.*session id: //' | awk '{{print $1}}'); "
                f'  echo "\\n--- {docs_label} が空. resume リトライ (SID=$SID) ---"; '
                f"  echo '{docs_label} が空のままです。調査結果を書き込んでください。' "
                f'| {cli_cmd} -r "$SID" -p --dangerously-skip-permissions '
                f"2>&1 | tee -a {log_q}; "
                f"fi; "
            )
        else:
            shell_cmd += (
                f"if [ ! -s {_q(docs_path)} ]; then "
                f"  SID=$(grep -m1 'session id: ' {log_q} | awk '{{print $3}}'); "
                f'  echo "\\n--- {docs_label} が空. resume リトライ (SID=$SID) ---"; '
                f'  {cli_cmd} exec resume "$SID" --full-auto '
                f'"{docs_label} が空のままです。調査結果を書き込んでください。" '
                f"2>&1 | tee -a {log_q}; "
                f"fi; "
            )
    if patch_path is not None:
        if is_claude:
            shell_cmd += (
                f"if [ ! -s {_q(patch_path)} ]; then "
                f"  SID=$(grep -m1 'session id: ' {log_q} | sed 's/.*session id: //' | awk '{{print $1}}'); "
                f'  echo "\\n--- パッチ未作成. コンテキスト注入 (SID=$SID) ---"; '
                f"  echo '{patch_label} が作成されていません。"
                f"住所の分割・修正が必要な場合はパッチファイルを作成してください。"
                f"現在の住所が正しい等の正当な理由がある場合は、その旨を {docs_label} に記載してください。' "
                f'| {cli_cmd} -r "$SID" -p --dangerously-skip-permissions '
                f"2>&1 | tee -a {log_q}; "
                f"fi; "
            )
        else:
            shell_cmd += (
                f"if [ ! -s {_q(patch_path)} ]; then "
                f"  SID=$(grep -m1 'session id: ' {log_q} | awk '{{print $3}}'); "
                f'  echo "\\n--- パッチ未作成. コンテキスト注入 (SID=$SID) ---"; '
                f'  {cli_cmd} exec resume "$SID" --full-auto '
                f'"{patch_label} が作成されていません。'
                f"住所の分割・修正が必要な場合はパッチファイルを作成してください。"
                f'現在の住所が正しい等の正当な理由がある場合は、その旨を {docs_label} に記載してください。" '
                f"2>&1 | tee -a {log_q}; "
                f"fi; "
            )
    if docs_path is not None or patch_path is not None:
        shell_cmd += 'echo "\\n--- 完了 ---"'
    return shell_cmd


def _launch_claude_direct(
    selected: list[dict[str, str]],
    prompts: dict[str, str],
    *,
    check_docs: bool = False,
    check_patch: bool = False,
) -> None:
    """claude -p を直接子プロセスとして順次実行する.

    claude -p は独立プロセス（kitty等）では並行セッション制限でハングするため、
    呼び出し元の直接子プロセスとして実行する必要がある。
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    allowed = "Read,Edit,Write,Bash,WebSearch,WebFetch,Glob,Grep"

    print(f"{len(selected)} 件を claude -p で順次実行します...\n")

    for i, t in enumerate(selected):
        code = t["code"]
        prompt = prompts[code]
        log_file = LOG_DIR / f"{timestamp}_{code}.log"
        prompt_file = LOG_DIR / f"{timestamp}_{code}.prompt.txt"
        prompt_file.write_text(prompt, encoding="utf-8")

        docs_md = PROJECT_ROOT / "split-address" / f"{code}.md"
        patch_yaml = PATCH_DIR / f"{code}.yaml"

        print(f"  [{i + 1}/{len(selected)}] {code} {t['name']}")
        print(f"      log: {log_file}", flush=True)

        with open(prompt_file, encoding="utf-8") as stdin_f, open(log_file, "w", encoding="utf-8") as log_f:
            result = subprocess.run(
                [
                    "claude",
                    "-p",
                    "--dangerously-skip-permissions",
                    "--allowedTools",
                    allowed,
                    "--disallowedTools",
                    "Bash(git:*)",
                    "--effort",
                    "max",
                    "--append-system-prompt",
                    "重要: 1) 必ずWebSearch/WebFetchで住所を調査すること"
                    " 2) 必ずBashでジオコード検証(TokyoGeocoder)を実行すること"
                    " 3) 必ずsplit-address/{code}.mdに推論メモを書くこと"
                    " 4) git commit/pushは絶対に実行しないこと",
                ],
                stdin=stdin_f,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                cwd=PROJECT_ROOT,
                env={**os.environ, "NO_COLOR": "1"},
            )

        rc = result.returncode
        status = "完了" if rc == 0 else f"エラー (code={rc})"
        print(f"      {status}")

        # docs / patch 検証
        if check_docs:
            if not docs_md.exists() or docs_md.stat().st_size == 0:
                # resume リトライ
                sid = _extract_session_id(log_file)
                if sid:
                    print(f"      split-address/{code}.md が空. resume リトライ (SID={sid})")
                    _claude_resume(
                        sid, f"split-address/{code}.md が空のままです。調査結果を書き込んでください。", log_file
                    )
                else:
                    print(f"      エラー - split-address/{code}.md が空です (推論メモ未保存)")

        if check_patch:
            if not patch_yaml.exists() or patch_yaml.stat().st_size == 0:
                sid = _extract_session_id(log_file)
                if sid:
                    print(f"      パッチ未作成. resume リトライ (SID={sid})")
                    _claude_resume(
                        sid,
                        f"config/address_patches/{code}.yaml が作成されていません。"
                        "住所の分割・修正が必要な場合はパッチファイルを作成してください。"
                        "現在の住所が正しい等の正当な理由がある場合は、"
                        f"その旨を split-address/{code}.md に記載してください。",
                        log_file,
                    )
                else:
                    print(f"      注意 - パッチ未作成 (address_patches/{code}.yaml)")

    print(f"\n=== 全 {len(selected)} 件完了 ===\n")
    return timestamp


def _extract_session_id(log_file: Path) -> str | None:
    """ログファイルから session id を抽出."""
    if not log_file.exists():
        return None
    try:
        # --output-format json の場合は JSON から取得
        import json as _json

        for line in log_file.read_text(encoding="utf-8").splitlines():
            if "session_id" in line:
                try:
                    data = _json.loads(line)
                    sid = data.get("session_id")
                    if sid:
                        return sid
                except _json.JSONDecodeError:
                    pass
            if "session id: " in line:
                return line.split("session id: ")[1].split()[0]
    except OSError:
        pass
    return None


def _claude_resume(session_id: str, message: str, log_file: Path) -> None:
    """claude --resume で追加指示を送信."""
    with open(log_file, "a", encoding="utf-8") as log_f:
        subprocess.run(
            ["claude", "-p", "--resume", session_id, "--allowedTools", "Read,Edit,Write,Bash,WebSearch,WebFetch"],
            input=message,
            text=True,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            cwd=PROJECT_ROOT,
            env={**os.environ, "NO_COLOR": "1"},
        )


def _terminal_cmd(title: str, script_file: Path) -> list[str]:
    """Build command to launch a script in a new terminal window."""
    if sys.platform == "win32":
        import shutil

        script_path = str(script_file)
        if shutil.which("wt"):
            return ["wt", "-w", "new", "--title", title, "--", "pwsh", "-NoProfile", "-File", script_path]
        # フォールバック: cmd /c start で新しいウィンドウを開く
        return ["cmd", "/c", "start", title, "pwsh", "-NoProfile", "-File", script_path]
    return ["kitty", "--title", title, "-e", "bash", str(script_file)]


def _collect_missing_artifacts(
    selected: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """未生成の .md / .yaml を持つ企業を収集."""
    missing_docs: list[dict[str, str]] = []
    missing_patches: list[dict[str, str]] = []
    for t in selected:
        code = t["code"]
        docs_md = PROJECT_ROOT / "split-address" / f"{code}.md"
        patch_yaml = PATCH_DIR / f"{code}.yaml"
        if not docs_md.exists() or docs_md.stat().st_size == 0:
            missing_docs.append(t)
        if not patch_yaml.exists() or patch_yaml.stat().st_size == 0:
            missing_patches.append(t)
    return missing_docs, missing_patches


def _build_recovery_prompt(
    selected: list[dict[str, str]],
    missing_docs: list[dict[str, str]],
    missing_patches: list[dict[str, str]],
) -> str:
    """欠損ファイル一覧をまとめたリカバリプロンプトを構築."""
    lines: list[str] = []
    lines.append("# split-address 実行結果レポート\n")
    lines.append(
        f"対象企業 {len(selected)} 件の並行調査が完了しましたが、"
        "一部の成果物が欠損しています。\n"
    )

    if missing_docs:
        lines.append("## 調査メモ未生成 (split-address/*.md)\n")
        for t in missing_docs:
            lines.append(
                f"- {t['code']} {t['name']}: "
                f"`split-address/{t['code']}.md` が空または未作成"
            )
        lines.append("")

    if missing_patches:
        lines.append("## パッチ未生成 (config/address_patches/*.yaml)\n")
        for t in missing_patches:
            docs_md = PROJECT_ROOT / "split-address" / f"{t['code']}.md"
            has_docs = docs_md.exists() and docs_md.stat().st_size > 0
            note = "調査メモあり → パッチ生成可能" if has_docs else "調査メモも未生成"
            lines.append(
                f"- {t['code']} {t['name']}: "
                f"`config/address_patches/{t['code']}.yaml` 未作成 ({note})"
            )
        lines.append("")

    lines.append("## 対処方法\n")
    lines.append(
        "調査メモ (`split-address/{code}.md`) が存在する企業については、"
        "その内容を元に `config/address_patches/{code}.yaml` を生成できます。"
    )
    lines.append(
        "パッチの書式は `config/address_overrides.yaml` の既存エントリを参考にしてください。\n"
    )
    lines.append("上記の欠損状況をユーザに報告し、どの企業から対処するか確認してください。")

    return "\n".join(lines)


def _launch_recovery_session(
    selected: list[dict[str, str]],
    missing_docs: list[dict[str, str]],
    missing_patches: list[dict[str, str]],
) -> None:
    """欠損ファイルの一覧を注入して claude を新規ターミナルで対話起動."""
    import shlex

    prompt = _build_recovery_prompt(selected, missing_docs, missing_patches)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prompt_file = LOG_DIR / f"{timestamp}_recovery.prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    if sys.platform == "win32":
        script = (
            f"cd '{PROJECT_ROOT}'\n"
            f"Get-Content '{prompt_file}' | claude\n"
            f"Read-Host 'Press Enter to close'\n"
        )
        script_file = LOG_DIR / f"{timestamp}_recovery.ps1"
        script_file.write_text(script, encoding="utf-8")
    else:
        script = (
            f"cd {shlex.quote(str(PROJECT_ROOT))} || exit 1\n"
            f"claude < {shlex.quote(str(prompt_file))}\n"
        )
        script_file = LOG_DIR / f"{timestamp}_recovery.sh"
        script_file.write_text(script, encoding="utf-8")

    cmd = _terminal_cmd("split-address recovery", script_file)
    subprocess.Popen(cmd, cwd=PROJECT_ROOT)
    print(f"  リカバリプロンプト: {prompt_file}")


def _post_process(timestamp: str, selected: list[dict[str, str]]) -> None:
    """パッチマージと run.py を実行する (lockdown 解除後に呼ぶ)."""
    # 欠損検出 → リカバリセッション起動
    missing_docs, missing_patches = _collect_missing_artifacts(selected)
    if missing_docs or missing_patches:
        n_docs = len(missing_docs)
        n_patches = len(missing_patches)
        print(f"\n=== 欠損検出: md={n_docs}, yaml={n_patches} → リカバリセッション起動 ===\n")
        _launch_recovery_session(selected, missing_docs, missing_patches)

    # パッチファイルが存在すればマージを自動実行
    patch_files = list(PATCH_DIR.glob("*.yaml"))
    if patch_files:
        print("=== パッチマージ実行 ===\n")
        subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "merge_address_patches.py")],
            cwd=PROJECT_ROOT,
        )
        print()

    print(f"ログ確認: ls {LOG_DIR}/{timestamp}_*.log")

    print("\n=== run.py 実行 ===\n")
    subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "run.py")],
        cwd=PROJECT_ROOT,
    )


def _launch_processes(
    selected: list[dict[str, str]],
    prompts: dict[str, str],
    cli_cmd: str,
    *,
    check_docs: bool = False,
    check_patch: bool = False,
) -> str:
    """Launch CLI processes. Returns timestamp for post-processing."""
    if cli_cmd == "claude":
        return _launch_claude_direct(selected, prompts, check_docs=check_docs, check_patch=check_patch)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    is_win = sys.platform == "win32"
    term_name = "Windows Terminal / pwsh" if is_win else "kitty"
    print(f"{len(selected)} プロセスを {term_name} ウィンドウで起動します...\n")

    def _pq(p: Path | str) -> str:
        """PowerShell 用シングルクォート (内部の ' を '' にエスケープ)."""
        return "'" + str(p).replace("'", "''") + "'"

    def _bq(p: Path | str) -> str:
        """bash 用 shlex.quote (forward slash 変換付き)."""
        import shlex

        return shlex.quote(str(p).replace("\\", "/"))

    running: list[dict] = []
    for i, t in enumerate(selected):
        code = t["code"]
        prompt = prompts[code]
        log_file = LOG_DIR / f"{timestamp}_{code}.log"

        # プロンプトをファイル経由で渡す (シェルエスケープ問題を回避)
        prompt_file = LOG_DIR / f"{timestamp}_{code}.prompt.txt"
        prompt_file.write_text(prompt, encoding="utf-8")

        title = f"{code} {t['name']}"
        docs_md_rel = f"split-address/{code}.md"
        patch_yaml_rel = f"config/address_patches/{code}.yaml"

        if is_win:
            shell_cmd = _build_ps1_script(
                cli_cmd,
                prompt_file,
                log_file,
                cwd=PROJECT_ROOT,
                docs_path=PROJECT_ROOT / docs_md_rel if check_docs else None,
                docs_label=docs_md_rel,
                patch_path=PROJECT_ROOT / patch_yaml_rel if check_patch else None,
                patch_label=patch_yaml_rel,
            )
            script_file = LOG_DIR / f"{timestamp}_{code}.ps1"
        else:
            shell_cmd = _build_bash_script(
                cli_cmd,
                prompt_file,
                log_file,
                cwd=PROJECT_ROOT,
                docs_path=PROJECT_ROOT / docs_md_rel if check_docs else None,
                docs_label=docs_md_rel,
                patch_path=PROJECT_ROOT / patch_yaml_rel if check_patch else None,
                patch_label=patch_yaml_rel,
                _q=_bq,
            )
            script_file = LOG_DIR / f"{timestamp}_{code}.sh"

        script_file.write_text(shell_cmd, encoding="utf-8")
        cmd = _terminal_cmd(title, script_file)

        print(f"  [{i + 1}] {title}")
        print(f"      log: {log_file}")

        launch_env = {**os.environ, "NO_COLOR": "1"}
        # Ensure npm global bin is on PATH (needed for codex CLI)
        if sys.platform == "win32":
            npm_global = Path(os.environ.get("APPDATA", "")) / "npm"
            if str(npm_global) not in launch_env.get("PATH", ""):
                launch_env["PATH"] = launch_env.get("PATH", "") + ";" + str(npm_global)
        proc = subprocess.Popen(
            cmd,
            cwd=PROJECT_ROOT,
            env=launch_env,
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
            docs_md = PROJECT_ROOT / "split-address" / f"{p['code']}.md"
            if not docs_md.exists():
                print(f"  {p['code']} {p['name']}: エラー - split-address/{p['code']}.md が存在しません")
            elif docs_md.stat().st_size == 0:
                print(f"  {p['code']} {p['name']}: エラー - split-address/{p['code']}.md が空です (推論メモ未保存)")
        if check_patch:
            patch_yaml = PATCH_DIR / f"{p['code']}.yaml"
            if not patch_yaml.exists():
                print(f"  {p['code']} {p['name']}: 注意 - パッチ未作成 (address_patches/{p['code']}.yaml)")

    print("\n=== 全プロセス完了 ===\n")
    return timestamp


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
