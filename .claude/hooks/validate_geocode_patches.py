#!/usr/bin/env python3
"""Stop hook: Validate geocode levels for all address patch files."""

import glob
import os
import sys

import yaml

sys.path.insert(0, os.environ.get("CLAUDE_PROJECT_DIR", "."))


def main() -> None:
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    patches = glob.glob(os.path.join(project_dir, "config/address_patches/*.yaml"))
    if not patches:
        return

    from src.geocode_tokyo import TokyoGeocoder

    geocoder = TokyoGeocoder(
        oaza_csv=os.path.join(
            project_dir,
            "data/geocoding/geocode_ref_oaza_chome_tokyo_2024/13_2024.csv",
        ),
        gaiku_csv=os.path.join(
            project_dir,
            "data/geocoding/geocode_ref_gaiku_tokyo_2024/13_2024.csv",
        ),
    )

    errors: list[str] = []
    for patch_file in patches:
        with open(patch_file) as f:
            data = yaml.safe_load(f)
        if not data:
            continue
        for code, sites in data.items():
            for site_name, addr_data in sites.items():
                addrs: list[str] = []
                if isinstance(addr_data, str):
                    addrs = [addr_data]
                elif isinstance(addr_data, list):
                    addrs = [
                        e.get("address", "")
                        for e in addr_data
                        if isinstance(e, dict)
                    ]
                for addr in addrs:
                    if not addr.startswith("東京都"):
                        continue
                    _lat, _lon, level = geocoder.geocode(addr)
                    if level != "gaiku":
                        errors.append(f"  {code}/{site_name}: {addr} → {level}")

    if errors:
        print(
            "GEOCODE WARNING: 以下の住所が gaiku レベルに到達しません:",
            file=sys.stderr,
        )
        for e in errors:
            print(e, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
