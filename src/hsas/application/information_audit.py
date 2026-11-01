"""Deterministic review of a merged candidate, separate from semantic accuracy."""

from collections import defaultdict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from hsas.application.notion_projection import expand_calendar, is_actionable
from hsas.domain.information import InformationStore


def audit_information(store: InformationStore) -> dict[str, Any]:
    """Expose omissions, weak provenance and projection expectations before write.

    This checks stored structure, not whether an Agent understood every source.
    Unknown deadlines remain tasks and never become fabricated calendar dates.
    """
    findings: list[dict[str, Any]] = []
    items = []
    duplicates: dict[tuple, list[str]] = defaultdict(list)
    zone = ZoneInfo(store.timezone)
    for item in store.items:
        value = item.model_dump(mode="json")
        actionable = is_actionable(value)
        occurrences = expand_calendar(value, store.timezone)
        codes = []
        if not any(source.url or source.relative_path for source in item.sources):
            codes.append("SOURCE_LOCATOR_MISSING")
        if actionable and not (item.due_at or item.due_on):
            # An exam/meeting can be actionable without a submission deadline.
            if not (item.starts_at or item.scheduled_on or item.recurrence):
                codes.append("ACTION_DATE_UNKNOWN")
        if item.date_status == "unknown" and occurrences:
            codes.append("DATED_WITH_UNKNOWN_STATUS")
        if item.due_at and item.due_on and item.due_at.astimezone(zone).date() != item.due_on:
            codes.append("DEADLINE_DATE_MISMATCH")
        if item.opens_at and item.due_at and item.opens_at > item.due_at:
            codes.append("OPENS_AFTER_DEADLINE")
        if item.opens_at and item.due_on and not item.due_at:
            if item.opens_at.astimezone(zone).date() > item.due_on:
                codes.append("OPENS_AFTER_DEADLINE")
        if item.recurrence and not occurrences:
            codes.append("RECURRENCE_HAS_NO_OCCURRENCES")
        if item.recurrence:
            for exception in item.recurrence.exceptions:
                if not any(s.url or s.relative_path for s in exception.sources):
                    codes.append("EXCEPTION_SOURCE_MISSING")
                    break
        if item.warnings:
            codes.append("SOURCE_WARNINGS_REQUIRE_REVIEW")
        findings.extend({"code": code, "item_id": item.item_id, "course_id": item.course_id,
                         "severity": "error" if code in {"DEADLINE_DATE_MISMATCH", "OPENS_AFTER_DEADLINE"} else "review"}
                        for code in codes)
        # Compare instants in the store timezone so alternate offsets cannot
        # hide duplicated records. This flags candidates, never deletes them.
        timing = tuple(
            (key, str(getattr(item, key).astimezone(zone))
             if isinstance(getattr(item, key), datetime) else value[key])
            for key in ("starts_at", "due_at", "due_on", "scheduled_on")
        )
        duplicates[(item.course_id, item.category, " ".join(item.title.casefold().split()),
                    timing, item.recurrence.model_dump_json() if item.recurrence else None)].append(item.item_id)
        items.append({"item_id": item.item_id, "course_id": item.course_id,
                      "actionable": actionable, "task_role": item.task_role,
                      "date_status": item.date_status,
                      "calendar_occurrence_ids": [row["identity"] for row in occurrences]})
    for ids in duplicates.values():
        if len(ids) > 1:
            findings.append({"code": "POSSIBLE_DUPLICATE_ITEMS", "item_ids": ids, "severity": "review"})
    return {
        "status": "needs_review" if findings else "checks_passed",
        "source_reading_verified": False,
        "semantic_accuracy_verified": False,
        "counts": {"items": len(items),
                   "actionable_items": sum(row["actionable"] for row in items),
                   "undated_actionable_items": sum(row["actionable"] and not row["calendar_occurrence_ids"]
                                                  for row in items),
                   "calendar_occurrences": sum(len(row["calendar_occurrence_ids"]) for row in items),
                   "findings": len(findings)},
        "items": items, "findings": findings,
    }


def blocking_update_findings(audit: dict[str, Any], item_ids: set[str]) -> list[dict[str, Any]]:
    """Reject inconsistent incoming dates while leaving unrelated old gaps visible."""
    return [finding for finding in audit["findings"]
            if finding["severity"] == "error" and finding.get("item_id") in item_ids]
