from __future__ import annotations

from pathlib import Path


def test_runtime_code_uses_stock_db_public_api() -> None:
    root = Path(__file__).resolve().parent.parent
    banned = (
        "STOCKS_DB_PATH",
        "stock_db.api",
        "stock_db.paths",
        "stock_db.storage",
        "stock_db.cli",
        "stock_db.sources",
        "scrape-stooq-prices",
    )
    checked_files = [
        root / "run.py",
        root / "src" / "stock_db_sync.py",
        root / "src" / "company_store.py",
        root / "scripts" / "populate_company_master.py",
        root / "scripts" / "populate_company_names.py",
    ]

    violations: list[str] = []
    for path in checked_files:
        text = path.read_text(encoding="utf-8")
        for token in banned:
            if token in text:
                violations.append(f"{path.relative_to(root)}: {token}")

    assert violations == []
