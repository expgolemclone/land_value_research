"""Merge individual address patch YAML files into address_overrides.yaml.

Reads all YAML files from config/address_patches/, merges them into
config/address_overrides.yaml (patch entries overwrite existing ones),
deletes merged patch files, and reports statistics.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import ADDRESS_OVERRIDES_PATH, DEFAULT_OUTPUT_DIR  # noqa: E402
from src.config import PATCH_DIR as _PATCH_DIR  # noqa: E402

OVERRIDES_FILE = ADDRESS_OVERRIDES_PATH
PATCH_DIR = _PATCH_DIR


def load_yaml(path: Path) -> dict:
    """Load a YAML file and return its content as a dict (empty dict if None)."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def _format_value_for_display(value: object) -> str:
    """Format an override value for display in logs/prints."""
    if isinstance(value, list):
        return f"(分割: {len(value)}件)"
    return str(value)


def save_yaml(path: Path, data: dict) -> None:
    """Save a dict to a YAML file with Japanese-friendly formatting."""
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(
            data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=True,
        )


def merge_patches_safe(
    patch_dir: Path | None = None,
    overrides_file: Path | None = None,
) -> int:
    """Merge address patches without sys.exit. Returns count of merged files.

    Safe to call from run.py pipeline. Does nothing if no patches exist.
    """
    _patch_dir = patch_dir or PATCH_DIR
    _overrides_file = overrides_file or OVERRIDES_FILE

    if not _patch_dir.exists():
        logger.debug("パッチディレクトリが存在しません: %s", _patch_dir)
        return 0

    patch_files = sorted(_patch_dir.glob("*.yaml"))
    if not patch_files:
        logger.debug("パッチファイルなし: %s", _patch_dir)
        return 0

    logger.info("アドレスパッチマージ開始: %d件", len(patch_files))

    overrides_raw = load_yaml(_overrides_file)
    overrides: dict[str, dict] = {str(k): v for k, v in overrides_raw.items()}
    added = 0
    updated = 0
    errors = 0
    affected_codes: set[str] = set()
    merged_patch_files: list[Path] = []

    for pf in patch_files:
        patch = load_yaml(pf)
        if not patch:
            logger.warning("スキップ (空): %s", pf.name)
            errors += 1
            continue

        logger.info("  処理中: %s", pf.name)

        for code, sites in patch.items():
            code_key = str(code)
            if not isinstance(sites, dict):
                logger.warning("  警告: %s の値が辞書ではありません。スキップ。", code)
                errors += 1
                continue

            affected_codes.add(code_key)

            if code_key in overrides:
                existing = overrides[code_key]
                if not isinstance(existing, dict):
                    existing = {}
                for site_name, address in sites.items():
                    if site_name in existing:
                        if existing[site_name] != address:
                            logger.info("  上書き: %s / %s", code, site_name)
                            updated += 1
                    else:
                        logger.info("  追加: %s / %s", code, site_name)
                        added += 1
                    existing[site_name] = address
                overrides[code_key] = existing
            else:
                overrides[code_key] = sites
                for site_name in sites:
                    logger.info("  追加: %s / %s", code, site_name)
                    added += 1

        merged_patch_files.append(pf)

    save_yaml(_overrides_file, overrides)
    for pf in merged_patch_files:
        pf.unlink()

    # マージで影響を受けた企業の output CSV を削除 (run.py で再計算させる)
    output_dir = DEFAULT_OUTPUT_DIR
    for code_key in sorted(affected_codes):
        csv_path = output_dir / f"{code_key}_output.csv"
        if csv_path.exists():
            csv_path.unlink()
            logger.info("  CSV削除 (再計算対象): %s", csv_path.name)

    logger.info("パッチマージ完了: 追加=%d, 上書き=%d, エラー=%d", added, updated, errors)
    return len(merged_patch_files)


def merge_patches() -> None:
    """Main merge logic (standalone CLI entry point)."""
    if not PATCH_DIR.exists():
        print(f"パッチディレクトリが存在しません: {PATCH_DIR}")
        sys.exit(1)

    patch_files = sorted(PATCH_DIR.glob("*.yaml"))
    if not patch_files:
        print(f"パッチファイルがありません: {PATCH_DIR}")
        sys.exit(0)

    print("=== address_overrides.yaml マージ ===")
    print(f"パッチファイル: {len(patch_files)} 件")
    print()

    overrides_raw = load_yaml(OVERRIDES_FILE)
    overrides: dict[str, dict] = {str(k): v for k, v in overrides_raw.items()}
    added = 0
    updated = 0
    errors = 0
    affected_codes: set[str] = set()
    merged_patch_files: list[Path] = []

    for pf in patch_files:
        patch = load_yaml(pf)
        if not patch:
            print(f"  スキップ (空): {pf.name}")
            errors += 1
            continue

        print(f"  処理中: {pf.name}")

        for code, sites in patch.items():
            code_key = str(code)
            if not isinstance(sites, dict):
                print(f"    警告: {code} の値が辞書ではありません。スキップ。")
                errors += 1
                continue

            affected_codes.add(code_key)

            if code_key in overrides:
                existing = overrides[code_key]
                if not isinstance(existing, dict):
                    existing = {}
                for site_name, address in sites.items():
                    if site_name in existing:
                        if existing[site_name] != address:
                            print(f"    上書き: {code} / {site_name}")
                            print(f"      旧: {_format_value_for_display(existing[site_name])}")
                            print(f"      新: {_format_value_for_display(address)}")
                            updated += 1
                        else:
                            print(f"    同一 (変更なし): {code} / {site_name}")
                    else:
                        print(f"    追加: {code} / {site_name}")
                        added += 1
                    existing[site_name] = address
                overrides[code_key] = existing
            else:
                overrides[code_key] = sites
                for site_name in sites:
                    print(f"    追加: {code} / {site_name}")
                    added += 1

        merged_patch_files.append(pf)

    print()

    # 保存
    save_yaml(OVERRIDES_FILE, overrides)
    print(f"マージ結果を保存しました: {OVERRIDES_FILE}")
    for pf in merged_patch_files:
        pf.unlink()
        print(f"    削除済み: {pf.name}")

    # マージで影響を受けた企業の output CSV を削除 (run.py で再計算させる)
    output_dir = DEFAULT_OUTPUT_DIR
    csv_deleted = 0
    for code_key in sorted(affected_codes):
        csv_path = output_dir / f"{code_key}_output.csv"
        if csv_path.exists():
            csv_path.unlink()
            print(f"    CSV削除 (再計算対象): {csv_path.name}")
            csv_deleted += 1

    print()
    print("--- 統計 ---")
    print(f"  新規追加: {added} 件")
    print(f"  上書き:   {updated} 件")
    if errors:
        print(f"  エラー:   {errors} 件")
    if csv_deleted:
        print(f"  CSV削除:  {csv_deleted} 件")
    print(f"  合計企業: {len(overrides)} 件 (address_overrides.yaml)")


if __name__ == "__main__":
    merge_patches()
