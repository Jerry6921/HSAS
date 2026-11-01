"""Read-only Apple delivery plan from the same calendar/task rules as Notion."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo

from hsas.application.notion_projection import expand_calendar, is_actionable
from hsas.domain.information import InformationStore


def build_apple_projection(store: InformationStore, namespace: str,
                           previous: dict[str, Any] | None = None,
                           *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    if now.utcoffset() is None:
        raise ValueError("Apple projection clock must include a UTC offset")
    zone = ZoneInfo(store.timezone)

    def upcoming(value: str, *, has_end: bool = False) -> bool:
        if len(value) == 10:
            return datetime.fromisoformat(value).date() >= now.astimezone(zone).date()
        moment = datetime.fromisoformat(value)
        return moment > now if has_end else moment >= now

    courses = {course.course_id: course for course in store.courses}
    events, reminders = [], []
    excluded_unconfirmed = expired_events = expired_reminders = 0
    for item in store.items:
        if item.date_status != "confirmed":
            excluded_unconfirmed += 1
            continue
        value = item.model_dump(mode="json")
        course = courses[item.course_id]
        # Detailed requirements/evidence stay in HIQS. Apple is a concise agenda.
        notes = (f"地点：{item.location}" if item.location else "")
        notes = notes.replace("[HIQS", "［HIQS").replace("[/HIQS]", "［/HIQS］")
        url = next((source.url for source in item.sources if source.url), None)
        for row in expand_calendar(value, store.timezone):
            if not upcoming(row["end"] or row["start"], has_end=bool(row["end"])):
                expired_events += 1
                continue
            events.append({"identity": f"{namespace}/event/{sha256(row['identity'].encode()).hexdigest()}",
                           "title": f"{course.code} · {row['title']}",
                           "start": row["start"], "end": row["end"],
                           "location": row["location"], "notes": "", "url": url})
        if is_actionable(value):
            due = value["due_at"] or value["due_on"] or value["starts_at"] or value["scheduled_on"]
            if not due or not upcoming(due):
                expired_reminders += bool(due)
                continue
            reminders.append({"identity": f"{namespace}/reminder/{sha256(item.item_id.encode()).hexdigest()}",
                              "title": f"{course.code} · {item.title}", "due": due,
                              "notes": notes, "url": url})
    dates = [datetime.fromisoformat(row["start"]).replace(tzinfo=None).date() for row in events]
    today = now.astimezone(zone).date()
    first, last = min(dates, default=today), max(dates, default=today)
    for key, target in (("window_start", "first"), ("window_end", "last")):
        if previous and previous.get(key):
            day = datetime.fromisoformat(previous[key]).date()
            if target == "first":
                first = min(first, day)
            else:
                last = max(last, day)
    return {"schema_version": "1.0", "namespace": namespace, "timezone": store.timezone,
            "delivery_policy": "confirmed_upcoming_brief_v1", "as_of": now.isoformat(),
            "source_updated_at": store.updated_at.isoformat(),
            "window_start": first.isoformat(), "window_end": last.isoformat(),
            "query_start": (first - timedelta(days=1)).isoformat(),
            "query_end": (last + timedelta(days=2)).isoformat(),
            "events": events, "reminders": reminders,
            "excluded": {"unconfirmed_items": excluded_unconfirmed,
                         "expired_events": expired_events, "expired_reminders": expired_reminders},
            "counts": {"events": len(events), "reminders": len(reminders),
                       "undated_reminders": sum(not row["due"] for row in reminders)}}
