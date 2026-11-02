"""Is Apple Calendar/Reminders keeping up with the validated facts?

Delivery is already automatic: the launchd worker watches ``information.json`` and
re-syncs on change and on its interval. What was missing is a statement of whether
the last delivery actually reflects the current facts. Without it, "delivered"
reads as "current" even when the facts changed a minute ago and the worker has not
run yet.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def build_delivery(
    apple_status: dict[str, Any] | None,
    *,
    information_updated_at: str | None,
) -> dict[str, Any]:
    """Describe whether Apple delivery reflects the current validated facts."""
    status = apple_status or {}
    if not status.get("configured"):
        return {
            "configured": False,
            "worker_loaded": False,
            "up_to_date_with_facts": False,
            "behind_facts": False,
            "why": "Apple delivery is not configured",
        }
    report = status.get("report") or status.get("last_sync") or {}
    worker = status.get("worker") or {}
    delivered_from = report.get("source_updated_at")
    facts_at = information_updated_at
    delivered_moment = _parse(delivered_from)
    facts_moment = _parse(facts_at)
    if facts_moment is None or delivered_moment is None:
        up_to_date = False
        behind = False
        why = "cannot compare delivery with the current facts (missing timestamp)"
    elif delivered_moment >= facts_moment:
        up_to_date = True
        behind = False
        why = "Apple reflects the current facts"
    else:
        up_to_date = False
        behind = True
        why = "facts changed after the last Apple delivery; the worker will catch up"
    return {
        "configured": True,
        "worker_loaded": bool(worker.get("loaded")),
        "status": report.get("status"),
        "last_delivered_at": report.get("as_of"),
        "last_delivered_from_facts_at": delivered_from,
        "facts_updated_at": facts_at,
        "counts": report.get("counts") or {},
        "verification": report.get("verification") or {},
        "errors": report.get("errors") or [],
        "up_to_date_with_facts": up_to_date,
        "behind_facts": behind,
        "why": why,
    }


__all__ = ["build_delivery"]
