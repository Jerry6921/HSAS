"""Export the validated HIQS information calendar as RFC 5545 data."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from hashlib import sha256
from zoneinfo import ZoneInfo

from hsas.domain.information import InformationItem, InformationStore, WeeklyRecurrence


WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def build_ics(store: InformationStore) -> str:
    """Return a deterministic iCalendar projection of all dated information items."""
    courses = {course.course_id: course for course in store.courses}
    stamp = store.updated_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//HIQS//HKU Information Query System//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape('HIQS Course Calendar')}",
        f"X-WR-TIMEZONE:{store.timezone}",
    ]
    for item in store.items:
        course = courses.get(item.course_id)
        summary = f"{course.code} · {item.title}" if course else item.title
        if item.recurrence is not None:
            lines.extend(_recurring_events(item, summary, store.timezone, stamp))
        else:
            event = _single_event(item, summary, store.timezone, stamp)
            if event:
                lines.extend(event)
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def _event_head(item: InformationItem, summary: str, stamp: str, suffix: str = "") -> list[str]:
    uid_value = sha256(f"{item.item_id}{suffix}".encode()).hexdigest()[:24]
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid_value}@hiqs.local",
        f"DTSTAMP:{stamp}",
        f"SUMMARY:{_escape(summary)}",
        f"CATEGORIES:{_escape(item.category)}",
    ]
    if item.location:
        lines.append(f"LOCATION:{_escape(item.location)}")
    description = _description(item)
    if description:
        lines.append(f"DESCRIPTION:{_escape(description)}")
    if item.links:
        lines.append(f"URL:{_escape(item.links[0].url)}")
    return lines


def _single_event(
    item: InformationItem,
    summary: str,
    timezone: str,
    stamp: str,
) -> list[str] | None:
    lines = _event_head(item, summary, stamp)
    if item.starts_at:
        lines.append(_datetime_line("DTSTART", item.starts_at, timezone))
        if item.ends_at:
            lines.append(_datetime_line("DTEND", item.ends_at, timezone))
    elif item.due_at:
        lines.append(_datetime_line("DTSTART", item.due_at, timezone))
    else:
        day = item.due_on or item.scheduled_on
        if day is None:
            return None
        lines.append(f"DTSTART;VALUE=DATE:{_date_value(day)}")
    lines.append("END:VEVENT")
    return lines


def _recurring_events(
    item: InformationItem,
    summary: str,
    timezone: str,
    stamp: str,
) -> list[str]:
    recurrence = item.recurrence
    assert recurrence is not None
    first_date = _first_occurrence(recurrence)
    lines = _event_head(item, summary, stamp)
    lines.extend(
        [
            _local_line("DTSTART", first_date, recurrence.start_time, timezone),
            _local_line("DTEND", first_date, recurrence.end_time, timezone),
            "RRULE:FREQ=WEEKLY;"
            f"BYDAY={','.join(WEEKDAYS[index] for index in recurrence.weekdays)};"
            f"UNTIL={_until_value(recurrence.valid_until, timezone)}",
        ]
    )
    cancelled = set(recurrence.excluded_dates)
    cancelled.update(
        exception.date for exception in recurrence.exceptions if exception.status == "cancelled"
    )
    changed_dates = {
        exception.date for exception in recurrence.exceptions if exception.status == "changed"
    }
    cancelled.update(changed_dates)
    if cancelled:
        values = ",".join(
            _local_value(value, recurrence.start_time) for value in sorted(cancelled)
        )
        lines.append(f"EXDATE;TZID={timezone}:{values}")
    if recurrence.additional_dates:
        values = ",".join(
            _local_value(value, recurrence.start_time)
            for value in sorted(recurrence.additional_dates)
        )
        lines.append(f"RDATE;TZID={timezone}:{values}")
    lines.append("END:VEVENT")

    for exception in recurrence.exceptions:
        if exception.status != "changed":
            continue
        start_time = exception.start_time or recurrence.start_time
        end_time = exception.end_time or recurrence.end_time
        override_summary = exception.title or summary
        override = _event_head(
            item,
            override_summary,
            stamp,
            suffix=f"-{exception.date.isoformat()}",
        )
        override.extend(
            [
                _local_line("DTSTART", exception.date, start_time, timezone),
                _local_line("DTEND", exception.date, end_time, timezone),
            ]
        )
        if exception.location:
            override = [
                line for line in override if not line.startswith("LOCATION:")
            ]
            override.append(f"LOCATION:{_escape(exception.location)}")
        if exception.note:
            override.append(f"X-HIQS-EXCEPTION-NOTE:{_escape(exception.note)}")
        override.append("END:VEVENT")
        lines.extend(override)
    return lines


def _first_occurrence(recurrence: WeeklyRecurrence) -> date:
    cursor = recurrence.valid_from
    while cursor.weekday() not in recurrence.weekdays:
        cursor = date.fromordinal(cursor.toordinal() + 1)
    return cursor


def _description(item: InformationItem) -> str:
    parts = [item.description or ""]
    if item.assessment_format:
        parts.append(f"Format: {item.assessment_format}")
    if item.weight_percent is not None:
        parts.append(f"Weight: {item.weight_percent:g}%")
    if item.requirements:
        parts.append("Requirements: " + "; ".join(item.requirements))
    if item.materials:
        parts.append("Materials: " + "; ".join(value.title for value in item.materials))
    return "\n".join(value for value in parts if value)


def _datetime_line(name: str, value: datetime, timezone: str) -> str:
    if value.utcoffset() == UTC.utcoffset(value):
        return f"{name}:{value.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    local = value.astimezone(ZoneInfo(timezone))
    return f"{name};TZID={timezone}:{local.strftime('%Y%m%dT%H%M%S')}"


def _until_value(day: date, timezone: str) -> str:
    end = datetime.combine(day, time(23, 59, 59), tzinfo=ZoneInfo(timezone))
    return end.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _local_line(name: str, day: date, value: time, timezone: str) -> str:
    return f"{name};TZID={timezone}:{_local_value(day, value)}"


def _local_value(day: date, value: time) -> str:
    return f"{day.strftime('%Y%m%d')}T{value.strftime('%H%M%S')}"


def _date_value(value: date) -> str:
    return value.strftime("%Y%m%d")


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def _fold(line: str) -> str:
    """Fold UTF-8 content lines at 75 octets without splitting code points."""
    chunks: list[str] = []
    current = ""
    limit = 75
    for character in line:
        candidate = current + character
        if current and len(candidate.encode("utf-8")) > limit:
            chunks.append(current)
            current = " " + character
            limit = 75
        else:
            current = candidate
    chunks.append(current)
    return "\r\n".join(chunks)
