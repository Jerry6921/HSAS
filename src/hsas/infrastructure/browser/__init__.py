"""Shared authenticated browser-session infrastructure."""

from __future__ import annotations

from typing import Any

__all__ = ["BrowserSessionBroker", "BrowserSyncSession"]


def __getattr__(name: str) -> Any:
    if name in {"BrowserSessionBroker", "BrowserSyncSession"}:
        from .session import BrowserSessionBroker, BrowserSyncSession

        return {
            "BrowserSessionBroker": BrowserSessionBroker,
            "BrowserSyncSession": BrowserSyncSession,
        }[name]
    raise AttributeError(name)
