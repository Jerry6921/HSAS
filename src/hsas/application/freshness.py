"""How old each source is, and whether that is too old to trust.

HIQS stores a capture timestamp per source but never interprets it. A reader then
has to subtract dates before trusting a deadline — and nobody does that reliably,
least of all an agent, which sees "updated_at: 2026-10-27T06:17:29Z" and reports
it as a fact. This module turns timestamps into an explicit judgement so every
surface (MCP, CLI, viewer) can say "stale" instead of "present".

The thresholds are per source, not global: a catalogue page barely changes, a
Moodle course changes weekly during term. Each one is a claim about how fast that
source goes out of date, and each is written down next to its reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

FRESH = "fresh"
STALE = "stale"
NEVER = "never"

#: Days after which a source is no longer trusted without a warning.
THRESHOLDS_DAYS: dict[str, float] = {
    # AI-written course facts: the thing every answer is grounded in.
    "information": 7.0,
    # Course activity, files and deadlines change during term.
    "moodle": 3.0,
    # Enrolment only moves at add/drop, but a wrong course list is expensive.
    "sis_enrollment": 7.0,
    # Timetable rooms and slots change rarely after the add/drop period.
    "class_planner": 7.0,
    # Official catalogue prose is near-static between years.
    "sis_course_info": 30.0,
}


@dataclass(frozen=True, slots=True)
class SourceFreshness:
    """One source's age, judged against its own threshold."""

    source: str
    captured_at: str | None
    age_days: float | None
    threshold_days: float
    state: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "captured_at": self.captured_at,
            "age_days": self.age_days,
            "threshold_days": self.threshold_days,
            "state": self.state,
        }


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        captured = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=UTC)
    return captured


#: Sources name their capture time differently; accept any of the known keys
#: rather than silently reporting "never collected" for a populated source.
TIMESTAMP_KEYS = ("synced_at", "observed_at", "collected_at", "updated_at")


def _snapshot_time(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in TIMESTAMP_KEYS:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return None


def _newest(values: list[object]) -> str | None:
    parsed = [(_parse(value), value) for value in values]
    known = [(moment, raw) for moment, raw in parsed if moment is not None]
    if not known:
        return None
    return str(max(known, key=lambda pair: pair[0])[1])


def evaluate(
    source: str,
    captured_at: object,
    *,
    now: datetime,
    threshold_days: float | None = None,
) -> SourceFreshness:
    """Judge one source. Unknown timestamps are ``never``, not ``fresh``."""
    threshold = THRESHOLDS_DAYS.get(source, 7.0) if threshold_days is None else threshold_days
    captured = _parse(captured_at)
    if captured is None:
        return SourceFreshness(
            source=source,
            captured_at=None,
            age_days=None,
            threshold_days=threshold,
            state=NEVER,
        )
    age_days = round(max(0.0, (now - captured).total_seconds()) / 86400, 1)
    return SourceFreshness(
        source=source,
        captured_at=str(captured_at),
        age_days=age_days,
        threshold_days=threshold,
        state=STALE if age_days > threshold else FRESH,
    )


def build_freshness(snapshot: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """Judge every source reachable from the information snapshot."""
    courses = snapshot.get("courses") or []
    moodle_captures = [
        (course.get("moodle") or {}).get("collected_at")
        for course in courses
        if isinstance(course, dict)
    ]
    captured = {
        "information": snapshot.get("updated_at"),
        "moodle": _newest(moodle_captures),
        "sis_enrollment": _snapshot_time(snapshot.get("sis_enrollment")),
        "class_planner": _snapshot_time(snapshot.get("class_planner")),
        "sis_course_info": _snapshot_time(snapshot.get("sis_course_info")),
    }
    entries = [
        evaluate(source, captured_at, now=now)
        for source, captured_at in captured.items()
    ]
    stale = [entry.source for entry in entries if entry.state == STALE]
    never = [entry.source for entry in entries if entry.state == NEVER]
    needs_sync = bool(stale or never)
    return {
        "evaluated_at": now.isoformat(),
        "needs_sync": needs_sync,
        "why": (
            "stale: " + ", ".join(stale)
            if stale
            else "never collected: " + ", ".join(never)
            if never
            else "all sources are within their freshness limit"
        ),
        "sources": [entry.as_dict() for entry in entries],
        "stale_sources": stale,
        "never_collected": never,
        "all_fresh": not needs_sync,
    }


__all__ = [
    "FRESH",
    "NEVER",
    "STALE",
    "THRESHOLDS_DAYS",
    "TIMESTAMP_KEYS",
    "SourceFreshness",
    "build_freshness",
    "evaluate",
]
