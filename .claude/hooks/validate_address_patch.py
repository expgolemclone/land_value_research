#!/usr/bin/env python3
"""PostToolUse hook: Validate address patch YAML files after writing."""

import json
import os
import sys

import yaml


def main() -> None:
    tool_input = json.loads(os.environ.get("CLAUDE_TOOL_INPUT", "{}"))
    file_path = tool_input.get("file_path", "")
    if "config/address_patches/" not in file_path or not file_path.endswith(".yaml"):
        return

    try:
        with open(file_path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"ERROR: YAML パースエラー: {e}", file=sys.stderr)
        sys.exit(2)

    if not isinstance(data, dict):
        print(
            f"ERROR: パッチファイルのルートは dict でなければなりません: {file_path}",
            file=sys.stderr,
        )
        sys.exit(2)

    for code, sites in data.items():
        if not isinstance(code, str):
            print(
                f"ERROR: 証券コードは文字列である必要があります: {code}",
                file=sys.stderr,
            )
            sys.exit(2)

        if not isinstance(sites, dict):
            print(f"ERROR: {code} の値は dict でなければなりません", file=sys.stderr)
            sys.exit(2)

        for site_name, addr_data in sites.items():
            if isinstance(addr_data, str):
                if not addr_data.startswith("東京都") and addr_data != "全国各所":
                    print(
                        f"WARNING: {code}/{site_name}: 住所が「東京都」で始まりません: {addr_data}",
                        file=sys.stderr,
                    )
            elif isinstance(addr_data, list):
                for entry in addr_data:
                    if not isinstance(entry, dict):
                        print(
                            f"ERROR: {code}/{site_name}: list の要素は dict でなければなりません",
                            file=sys.stderr,
                        )
                        sys.exit(2)
                    if "address" not in entry:
                        print(
                            f"ERROR: {code}/{site_name}: address が必須です",
                            file=sys.stderr,
                        )
                        sys.exit(2)

    print(f"OK: パッチファイル検証完了: {file_path}")


if __name__ == "__main__":
    main()
