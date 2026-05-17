"""Merge L01 (公示地価) and L02 (基準地価) GeoJSON files.

L01 features are kept as-is. L02 features whose coordinates overlap
with L01 (within 5 decimal places) are dropped. Non-overlapping L02
features have their properties renamed to L01 field names so that the
downstream Rust landprice engine can consume them transparently.

Usage:
    python scripts/merge_landprice.py [--l01 PATH] [--l02 PATH] [-o PATH]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# L02 -> L01 field mapping (only the fields consumed by landprice_tokyo.rs)
_L02_TO_L01 = {
    "L02_020": "L01_001",  # 都道府県市区町村コード
    "L02_001": "L01_002",  # 地点番号1
    "L02_002": "L01_003",  # 地点番号2
    "L02_006": "L01_008",  # 価格 (円/m²)
    "L02_046": "L01_051",  # 用途地域
}


def _coord_key(feat: dict) -> tuple[float, float]:
    c = feat["geometry"]["coordinates"]
    return (round(c[0], 5), round(c[1], 5))


def merge(l01_path: str, l02_path: str, out_path: str) -> dict:
    with open(l01_path, encoding="utf-8") as f:
        l01 = json.load(f)
    with open(l02_path, encoding="utf-8") as f:
        l02 = json.load(f)

    l01_coords = {_coord_key(feat) for feat in l01["features"]}

    merged_features = list(l01["features"])
    skipped = 0
    added = 0

    for feat in l02["features"]:
        if _coord_key(feat) in l01_coords:
            skipped += 1
            continue

        # Remap L02 properties to L01 field names
        old_props = feat["properties"]
        new_props = {}
        for l02_key, l01_key in _L02_TO_L01.items():
            if l02_key in old_props:
                new_props[l01_key] = old_props[l02_key]

        merged_features.append(
            {
                "type": "Feature",
                "geometry": feat["geometry"],
                "properties": new_props,
            }
        )
        added += 1

    result = {
        "type": "FeatureCollection",
        "features": merged_features,
    }

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)

    stats = {"l01": len(l01["features"]), "l02": len(l02["features"]),
             "skipped": skipped, "added": added, "total": len(merged_features)}
    return stats


def main() -> None:
    base = Path(__file__).resolve().parent.parent / "data" / "landprice"
    parser = argparse.ArgumentParser(description="Merge L01 + L02 GeoJSON")
    parser.add_argument("--l01", default=str(base / "tokyo_2025" / "L01-25_13.geojson"))
    parser.add_argument("--l02", default=str(base / "chika_chousa_2024" / "L02-24_13.geojson"))
    from src.config import GEOJSON_PATH
    parser.add_argument("-o", "--output", default=str(GEOJSON_PATH))
    args = parser.parse_args()

    stats = merge(args.l01, args.l02, args.output)
    print(f"L01: {stats['l01']}  L02: {stats['l02']}")
    print(f"Skipped (overlap): {stats['skipped']}  Added (L02-only): {stats['added']}")
    print(f"Total merged: {stats['total']}")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
