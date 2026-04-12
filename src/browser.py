"""Browser service client — delegates to stock_db.browser."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from stock_db.browser import (  # noqa: F401
    BrowserConfig,
    BrowserResponse,
    BrowserServiceError,
    build_proxy_fields,
)
from stock_db.browser import BrowserService as _BrowserService

from src.config import MAGIC

_BROWSER_SERVICE_DIR: Path = Path(__file__).resolve().parent.parent / "browser_service"


class BrowserService(_BrowserService):
    def __init__(self) -> None:
        super().__init__(
            config=cast(BrowserConfig, MAGIC["browser"]),
            browser_service_dir=_BROWSER_SERVICE_DIR,
        )
