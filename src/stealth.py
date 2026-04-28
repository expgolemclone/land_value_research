"""Proxy pool compatibility wrapper backed by stock_db.proxy_pool."""

from __future__ import annotations

from stock_db.proxy_pool import (  # noqa: F401
    ProxyPool,
    ProxyUnavailableError,
    random_delay,
)
