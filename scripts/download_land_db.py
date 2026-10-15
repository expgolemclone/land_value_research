from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> None:
    from src.config import LAND_DB_ASSET_URL, LAND_DB_PATH
    from src.land_db.asset import download_land_db

    parser = argparse.ArgumentParser(description="GitHub Release asset から data/land.db を取得する")
    parser.add_argument("--force", action="store_true", help="既存の data/land.db を上書きする")
    args = parser.parse_args()

    path = download_land_db(db_path=LAND_DB_PATH, force=args.force)
    print(f"land.db を配置しました: {path}")
    print(f"取得元: {LAND_DB_ASSET_URL}")


if __name__ == "__main__":
    main()
