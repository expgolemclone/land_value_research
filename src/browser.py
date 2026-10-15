"""Browser service compatibility wrapper backed by stock_db.browser_client."""

from __future__ import annotations

from typing import cast

from stock_db.browser_client.client import (
    BrowserConfig,
    BrowserResponse,
    BrowserServiceClient,
    BrowserServiceError,
)

from src.config import MAGIC

__all__ = ["BrowserResponse", "BrowserService", "BrowserServiceError"]


class BrowserService(BrowserServiceClient):
    def __init__(self) -> None:
        super().__init__(config=cast(BrowserConfig, MAGIC["browser"]))
