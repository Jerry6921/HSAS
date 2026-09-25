"""Cooperative cancellation shared by Moodle discovery and download stages."""

from __future__ import annotations

from collections.abc import Callable


class MoodleSyncCancelled(RuntimeError):
    """Raised at a safe synchronization boundary after cancellation is requested."""


def raise_if_cancelled(cancel_requested: Callable[[], bool] | None) -> None:
    if cancel_requested is not None and cancel_requested():
        raise MoodleSyncCancelled("Moodle synchronization was cancelled")
