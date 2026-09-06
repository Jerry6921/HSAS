"""Stage, preview, and apply user-provided information updates."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from hsas.application.ports.define_repositories import (
    InformationRepository,
    PersonalInboxRepository,
)
from hsas.application.update_information import (
    InformationApplyResult,
    apply_information_update,
    load_information,
    validate_information_update,
)
from hsas.domain.information import (
    InformationStore,
    PersonalInbox,
    PersonalInboxEntry,
)


INBOX_PATH = Path("ai-state/personal-inbox.json")


class PersonalInboxError(ValueError):
    """An invalid, missing, or unauthorized personal inbox operation."""


def load_personal_inbox(
    resources_dir: Path,
    repository: PersonalInboxRepository,
) -> PersonalInbox:
    path = resources_dir / INBOX_PATH
    if not repository.exists(path):
        return PersonalInbox()
    try:
        return repository.load(path)
    except (OSError, ValueError, ValidationError) as exc:
        raise PersonalInboxError(f"Personal inbox is invalid: {type(exc).__name__}") from exc


def add_personal_inbox_entry(
    resources_dir: Path,
    payload: Any,
    *,
    title: str,
    note: str | None = None,
    entry_id: str | None = None,
    repository: PersonalInboxRepository,
) -> PersonalInboxEntry:
    update = validate_information_update(payload)
    if not update.courses and not update.items:
        raise PersonalInboxError("Personal inbox update must contain a course or item")
    normalized_title = title.strip()
    if not normalized_title:
        raise PersonalInboxError("Personal inbox title is required")
    inbox = load_personal_inbox(resources_dir, repository)
    identifier = entry_id or f"personal-{datetime.now(UTC):%Y%m%d%H%M%S}-{uuid4().hex[:8]}"
    if any(entry.entry_id == identifier for entry in inbox.entries):
        raise PersonalInboxError(f"Personal inbox entry already exists: {identifier}")
    entry = PersonalInboxEntry(
        entry_id=identifier,
        title=normalized_title,
        note=note.strip() if note and note.strip() else None,
        created_at=datetime.now(UTC),
        update=update,
    )
    updated = inbox.model_copy(
        update={"updated_at": datetime.now(UTC), "entries": [*inbox.entries, entry]}
    )
    repository.save(resources_dir / INBOX_PATH, updated)
    return entry


def personal_inbox_snapshot(
    resources_dir: Path,
    *,
    information: InformationStore | None = None,
    inbox_repository: PersonalInboxRepository,
    information_repository: InformationRepository,
) -> dict[str, Any]:
    inbox = load_personal_inbox(resources_dir, inbox_repository)
    current = information or _load_information(resources_dir, information_repository)
    pending = [entry for entry in inbox.entries if entry.status == "pending"]
    return {
        "pending_count": len(pending),
        "entries": [preview_personal_inbox_entry(entry, current) for entry in pending],
    }


def preview_personal_inbox_entry(
    entry: PersonalInboxEntry,
    current: InformationStore,
) -> dict[str, Any]:
    course_by_id = {course.course_id: course for course in current.courses}
    item_by_id = {item.item_id: item for item in current.items}
    changes = []
    for record_type, records, existing in (
        ("course", entry.update.courses, course_by_id),
        ("item", entry.update.items, item_by_id),
    ):
        for record in records:
            identifier = record.course_id if record_type == "course" else record.item_id
            before = existing.get(identifier)
            changes.append(
                {
                    "record_type": record_type,
                    "record_id": identifier,
                    "title": record.title,
                    "action": "update" if before else "create",
                    "fields": _changed_fields(
                        before.model_dump(mode="json") if before else {},
                        record.model_dump(mode="json"),
                    ),
                }
            )
    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "note": entry.note,
        "created_at": entry.created_at.isoformat(),
        "status": entry.status,
        "changes": changes,
    }


def apply_personal_inbox_entry(
    resources_dir: Path,
    entry_id: str,
    *,
    confirmed: bool,
    inbox_repository: PersonalInboxRepository,
    information_repository: InformationRepository,
) -> InformationApplyResult:
    if not confirmed:
        raise PersonalInboxError("Personal inbox apply requires confirmation")
    inbox = load_personal_inbox(resources_dir, inbox_repository)
    entry = next((value for value in inbox.entries if value.entry_id == entry_id), None)
    if entry is None:
        raise PersonalInboxError(f"Personal inbox entry was not found: {entry_id}")
    if entry.status != "pending":
        raise PersonalInboxError(f"Personal inbox entry is already applied: {entry_id}")
    result = apply_information_update(
        resources_dir / "information.json",
        entry.update.model_dump(mode="json"),
        confirmed=True,
        repository=information_repository,
    )
    now = datetime.now(UTC)
    applied = entry.model_copy(update={"status": "applied", "applied_at": now})
    entries = [applied if value.entry_id == entry_id else value for value in inbox.entries]
    inbox_repository.save(
        resources_dir / INBOX_PATH,
        inbox.model_copy(update={"updated_at": now, "entries": entries}),
    )
    return result


def _load_information(
    resources_dir: Path,
    repository: InformationRepository,
) -> InformationStore:
    return load_information(resources_dir / "information.json", repository)


def _changed_fields(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    fields = []
    for key in sorted(set(before) | set(after)):
        previous = before.get(key)
        current = after.get(key)
        if previous == current:
            continue
        if not before and current in (None, [], {}, ""):
            continue
        fields.append({"field": key, "before": previous, "after": current})
    return fields
