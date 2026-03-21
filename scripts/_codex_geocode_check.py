# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.geocode_tokyo import TokyoGeocoder
from src.paths import GAIKU_CSV, OAZA_CSV


def main(argv: list[str]) -> int:
    addrs = argv[1:]
    if not addrs:
        print("usage: uv run python scripts/_codex_geocode_check.py <addr> [<addr> ...]")
        return 2

    geocoder = TokyoGeocoder(
        oaza_csv=str(OAZA_CSV),
        gaiku_csv=str(GAIKU_CSV),
    )

    for addr in addrs:
        lat, lon, level = geocoder.geocode(addr)
        print(f"{addr}\t{level}\t{lat}\t{lon}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
