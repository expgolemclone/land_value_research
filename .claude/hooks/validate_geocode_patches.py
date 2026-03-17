#!/usr/bin/env python3
"""Stop hook: Validate geocode levels for all address patch files."""

import os
import shutil
import sys


def _ensure_project_env() -> None:
    """Re-exec with venv or nix develop python if not already in project env."""
    if sys.prefix != sys.base_prefix:
        return
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    if sys.platform == "win32":
        venv_python = os.path.join(project_dir, ".venv", "Scripts", "python.exe")
    else:
        venv_python = os.path.join(project_dir, ".venv", "bin", "python")
    if os.path.isfile(venv_python):
        os.execv(venv_python, [venv_python] + sys.argv)
    elif shutil.which("nix"):
        os.execvp(
            "nix",
            ["nix", "develop", project_dir, "--command", "python3"] + sys.argv,
        )


_ensure_project_env()
sys.path.insert(0, os.environ.get("CLAUDE_PROJECT_DIR", "."))


def main() -> None:
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    overrides_file = os.path.join(project_dir, "config", "address_overrides.yaml")
    if not os.path.isfile(overrides_file):
        return

    import yaml

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

    with open(overrides_file) as f:
        data = yaml.safe_load(f)
    if not data:
        return

    errors: list[str] = []
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
