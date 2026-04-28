"""Browser service compatibility wrapper backed by stock_db.browser_client."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from stock_db.browser_client.client import (
    BrowserConfig,
    BrowserResponse,
    BrowserServiceClient,
    BrowserServiceError,
    build_proxy_fields,
)

from src.config import MAGIC

_BROWSER_SERVICE_DIR: Path = Path(__file__).resolve().parent.parent / "browser_service"


class BrowserService(BrowserServiceClient):
    def __init__(self) -> None:
        super().__init__(
            config=cast(BrowserConfig, MAGIC["browser"]),
            browser_service_dir=_BROWSER_SERVICE_DIR,
        )
