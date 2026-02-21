"""Merge individual address patch YAML files into address_overrides.yaml.

Reads all YAML files from config/address_patches/, merges them into
config/address_overrides.yaml (patch entries overwrite existing ones),
deletes merged patch files, and reports statistics.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OVERRIDES_FILE = PROJECT_ROOT / "config" / "address_overrides.yaml"
PATCH_DIR = PROJECT_ROOT / "config" / "address_patches"


def load_yaml(path: Path) -> dict:
    """Load a YAML file and return its content as a dict (empty dict if None)."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


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


def merge_patches() -> None:
    """Main merge logic."""
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

            if code_key in overrides:
                existing = overrides[code_key]
                if not isinstance(existing, dict):
                    existing = {}
                for site_name, address in sites.items():
                    if site_name in existing:
                        if existing[site_name] != address:
                            print(f"    上書き: {code} / {site_name}")
                            print(f"      旧: {existing[site_name]}")
                            print(f"      新: {address}")
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
    print()
    print("--- 統計 ---")
    print(f"  新規追加: {added} 件")
    print(f"  上書き:   {updated} 件")
    if errors:
        print(f"  エラー:   {errors} 件")
    print(f"  合計企業: {len(overrides)} 件 (address_overrides.yaml)")


if __name__ == "__main__":
    merge_patches()
