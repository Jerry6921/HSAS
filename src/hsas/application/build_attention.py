"""Derive actionable academic attention signals without mutating course facts."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
import json
from typing import Any, cast
from zoneinfo import ZoneInfo

from hsas.domain.information import (
    AttentionAction,
    AttentionEvidence,
    AttentionItem,
    AttentionReason,
    AttentionSeverity,
    AttentionSnapshot,
)

ASSESSMENT_CATEGORIES = {
    "assignment",
    "quiz",
    "exam",
    "presentation",
    "project",
    "report",
    "deadline",
}
CONFLICT_MARKERS = ("conflict", "disagree", "inconsistent", "冲突", "不一致")
UNRESOLVED_MARKERS = (
    "unresolved",
    "incomplete",
    "not submitted",
    "overdue",
    "未解决",
    "未完成",
    "未提交",
    "逾期",
)
SEVERITY_RANK: dict[AttentionSeverity, int] = {"high": 0, "medium": 1, "low": 2}


def build_attention_snapshot(
    information: dict[str, Any],
    *,
    now: datetime,
    horizon_days: int = 14,
) -> dict[str, Any]:
    """Build one deterministic packet for every delivery adapter.

    ``information`` is the existing dashboard read model. Missing source coverage is
    deliberately ignored; only explicit warnings and operational failures become
    attention signals.
    """
    if now.tzinfo is None:
        raise ValueError("now must include a UTC offset")
    if not 1 <= horizon_days <= 90:
        raise ValueError("horizon_days must be between 1 and 90")

    timezone = ZoneInfo(str(information.get("timezone") or "Asia/Hong_Kong"))
    current = now.astimezone(timezone)
    horizon = current + timedelta(days=horizon_days)
    recent = current - timedelta(days=horizon_days)
    courses = {
        str(course.get("course_id")): course
        for course in information.get("courses", [])
        if isinstance(course, dict) and course.get("course_id")
    }
    attention: list[AttentionItem] = []

    changed_by_item, changed_courses = _pending_changes(information)
    for raw in information.get("items", []):
        if not isinstance(raw, dict) or not raw.get("item_id"):
            continue
        item_id = str(raw["item_id"])
        course_id = str(raw.get("course_id") or "") or None
        course = courses.get(course_id or "", {})
        category = str(raw.get("category") or "")
        assessment = category in ASSESSMENT_CATEGORIES
        due_at = _primary_datetime(raw, timezone)
        in_horizon = due_at is not None and current <= due_at <= horizon
        recently_overdue = due_at is not None and recent <= due_at < current
        reasons: list[AttentionReason] = []
        missing_fields: list[str] = []
        warnings = [str(value) for value in raw.get("warnings", []) if value]
        conflicts = any(
            marker in warning.casefold()
            for warning in warnings
            for marker in CONFLICT_MARKERS
        )
        conflict_in_scope = conflicts and (
            due_at is None or recent <= due_at <= horizon
        )

        if assessment and raw.get("date_status") == "unknown":
            reasons.append("DUE_DATE_UNKNOWN")
        if in_horizon and raw.get("date_status") == "tentative":
            reasons.append("DUE_DATE_TENTATIVE")
        if assessment and in_horizon:
            if raw.get("due_on") and not raw.get("due_at"):
                missing_fields.append("due_time")
            submission_method = str(raw.get("submission_method") or "")
            if not submission_method:
                missing_fields.append("submission_method")
            if not raw.get("links") and any(
                marker in submission_method.casefold()
                for marker in ("moodle", "online", "turnitin", "upload", "form", "线上", "提交系统")
            ):
                missing_fields.append("submission_link")
            if missing_fields:
                reasons.append("SUBMISSION_DETAILS_MISSING")
            if raw.get("weight_percent") is None:
                reasons.append("WEIGHT_UNKNOWN")
        if conflict_in_scope:
            reasons.append("SOURCE_CONFLICT")
        if item_id in changed_by_item:
            reasons.append("SOURCE_CHANGED_REVIEW_PENDING")
            changed_courses.discard(changed_by_item[item_id])
        explicitly_unresolved = any(
            marker in warning.casefold()
            for warning in warnings
            for marker in UNRESOLVED_MARKERS
        )
        if assessment and recently_overdue and explicitly_unresolved:
            reasons.append("OVERDUE_UNRESOLVED")
        if not reasons:
            continue

        evidence = _evidence(raw)
        source_types = sorted({entry.source_type for entry in evidence})
        actions = [AttentionAction(kind="open_item", item_id=item_id)]
        if evidence:
            actions.append(
                AttentionAction(kind="open_evidence", item_id=item_id, evidence_index=0)
            )
        if "SOURCE_CHANGED_REVIEW_PENDING" in reasons:
            actions.append(AttentionAction(kind="review_changes", item_id=item_id))
        attention.append(
            _attention_item(
                attention_id=f"item:{item_id}",
                course_id=course_id,
                course=course,
                information_item_id=item_id,
                title=str(raw.get("title") or item_id),
                severity=_item_severity(reasons, due_at, current),
                reasons=reasons,
                due_at=due_at,
                date_status=str(raw.get("date_status") or "unknown"),
                missing_fields=missing_fields,
                conflicting_sources=source_types if conflict_in_scope else [],
                evidence=evidence,
                actions=actions,
            )
        )

    for course_id in sorted(changed_courses):
        course = courses.get(course_id, {})
        attention.append(
            _attention_item(
                attention_id=f"review:{course_id}",
                course_id=course_id or None,
                course=course,
                title=str(course.get("title") or course.get("code") or course_id),
                severity="medium",
                reasons=["SOURCE_CHANGED_REVIEW_PENDING"],
                affected_source="moodle",
                actions=[AttentionAction(kind="review_changes", source="moodle")],
            )
        )

    for task in _retry_tasks(information):
        source = str(task.get("source") or "unknown")
        course_id = str(task.get("course_id") or task.get("course_code") or "") or None
        course = _course_for_id_or_code(courses, course_id)
        suffix = course_id or str(task.get("stage") or "global")
        attention.append(
            _attention_item(
                attention_id=f"sync:{source}:{suffix}",
                course_id=str(course.get("course_id") or course_id or "") or None,
                course=course,
                title=str(task.get("title") or course.get("title") or f"{source} sync"),
                severity="medium",
                reasons=["SOURCE_SYNC_FAILED"],
                affected_source=source,
                actions=[AttentionAction(kind="retry_source", source=source)],
            )
        )

    moodle = information.get("moodle_session") or {}
    login_status = str(moodle.get("login_status") or "unknown")
    if login_status in {"expired", "login_required", "logged_out"}:
        attention.append(
            _attention_item(
                attention_id="login:moodle",
                title="Moodle",
                severity="medium",
                reasons=["LOGIN_REQUIRED"],
                affected_source="moodle",
                actions=[AttentionAction(kind="login_source", source="moodle")],
            )
        )

    attention.sort(
        key=lambda item: (
            SEVERITY_RANK[item.severity],
            item.due_at or datetime.max.replace(tzinfo=UTC),
            item.attention_id,
        )
    )
    counts: dict[AttentionSeverity, int] = {
        severity: sum(item.severity == severity for item in attention)
        for severity in cast(tuple[AttentionSeverity, ...], ("high", "medium", "low"))
    }
    return AttentionSnapshot(
        generated_at=now,
        horizon_days=horizon_days,
        items=attention,
        counts=counts,
    ).model_dump(mode="json")


def _primary_datetime(item: dict[str, Any], timezone: ZoneInfo) -> datetime | None:
    for field in ("due_at", "starts_at", "scheduled_on", "due_on", "opens_at"):
        value = item.get(field)
        if not value:
            continue
        if field in {"scheduled_on", "due_on"}:
            parsed_date = date.fromisoformat(str(value))
            return datetime.combine(parsed_date, time(23, 59), timezone)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone)
    return None


def _evidence(item: dict[str, Any]) -> list[AttentionEvidence]:
    result = []
    for source in item.get("sources", []):
        if not isinstance(source, dict):
            continue
        result.append(
            AttentionEvidence(
                source_type=str(source.get("source_type") or "other"),
                title=str(source.get("title") or "Source"),
                url=source.get("url"),
                relative_path=source.get("relative_path"),
                page_numbers=list(source.get("page_numbers") or []),
                note=source.get("note"),
            )
        )
    return result


def _pending_changes(information: dict[str, Any]) -> tuple[dict[str, str], set[str]]:
    changed_items: dict[str, str] = {}
    changed_courses: set[str] = set()
    updates = information.get("updates") or {}
    for course in updates.get("courses", []):
        if not isinstance(course, dict):
            continue
        course_id = str(course.get("course_id") or "")
        if course_id:
            changed_courses.add(course_id)
        changed_items.update(
            {
                str(value): course_id
                for value in course.get("affected_information_item_ids", [])
                if value
            }
        )
    return changed_items, changed_courses


def _retry_tasks(information: dict[str, Any]) -> list[dict[str, Any]]:
    closure = information.get("review_closure") or {}
    return [task for task in closure.get("retry_tasks", []) if isinstance(task, dict)]


def _course_for_id_or_code(
    courses: dict[str, dict[str, Any]],
    identity: str | None,
) -> dict[str, Any]:
    if not identity:
        return {}
    if identity in courses:
        return courses[identity]
    normalized = identity.casefold().replace(" ", "")
    return next(
        (
            course
            for course in courses.values()
            if str(course.get("code") or "").casefold().replace(" ", "") == normalized
        ),
        {},
    )


def _item_severity(
    reasons: list[AttentionReason],
    due_at: datetime | None,
    now: datetime,
) -> AttentionSeverity:
    if "OVERDUE_UNRESOLVED" in reasons:
        return "high"
    if "SOURCE_CONFLICT" in reasons and (
        due_at is None or due_at <= now + timedelta(days=7)
    ):
        return "high"
    if any(
        reason in reasons
        for reason in (
            "DUE_DATE_TENTATIVE",
            "SUBMISSION_DETAILS_MISSING",
            "SOURCE_CONFLICT",
            "SOURCE_CHANGED_REVIEW_PENDING",
        )
    ):
        return "medium"
    return "low"


def _attention_item(
    *,
    attention_id: str,
    title: str,
    severity: AttentionSeverity,
    reasons: list[AttentionReason],
    course_id: str | None = None,
    course: dict[str, Any] | None = None,
    information_item_id: str | None = None,
    due_at: datetime | None = None,
    date_status: str | None = None,
    missing_fields: list[str] | None = None,
    conflicting_sources: list[str] | None = None,
    affected_source: str | None = None,
    evidence: list[AttentionEvidence] | None = None,
    actions: list[AttentionAction] | None = None,
) -> AttentionItem:
    payload = {
        "attention_id": attention_id,
        "course_id": course_id,
        "information_item_id": information_item_id,
        "reasons": reasons,
        "due_at": due_at.isoformat() if due_at else None,
        "missing_fields": missing_fields or [],
        "conflicting_sources": conflicting_sources or [],
        "affected_source": affected_source,
        "evidence": [entry.model_dump(mode="json") for entry in evidence or []],
    }
    fingerprint = sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    course = course or {}
    return AttentionItem(
        attention_id=attention_id,
        fingerprint=fingerprint,
        course_id=course_id,
        course_code=course.get("code"),
        course_title=course.get("title"),
        information_item_id=information_item_id,
        title=title,
        severity=severity,
        reason_codes=list(dict.fromkeys(reasons)),
        due_at=due_at,
        date_status=date_status,
        missing_fields=list(dict.fromkeys(missing_fields or [])),
        conflicting_sources=conflicting_sources or [],
        affected_source=affected_source,
        evidence=evidence or [],
        actions=actions or [],
    )
