"""Manage staged personal-information updates behind the CORE port."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

from hsas.application.manage_inbox import (
    PersonalInboxError,
    add_personal_inbox_entry,
    apply_personal_inbox_entry,
    load_personal_inbox,
    personal_inbox_snapshot,
)
from hsas.application.ports.define_repositories import (
    InformationRepository,
    PersonalInboxRepository,
)
from hsas.core.define_port import HIQSPortError
from hsas.domain.information import InformationStore
from hsas.infrastructure.storage import (
    JsonInformationRepository,
    JsonPersonalInboxRepository,
)


@dataclass(slots=True)
class PersonalInboxService:
    """Stage, preview, inspect, and apply personal information drafts."""

    resources_dir: Path
    mutation_lock: Lock
    inbox_repository: PersonalInboxRepository = field(
        default_factory=JsonPersonalInboxRepository,
        repr=False,
    )
    information_repository: InformationRepository = field(
        default_factory=JsonInformationRepository,
        repr=False,
    )

    def apply(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirmed") is not True:
            raise HIQSPortError("请先确认写入个人补充信息。")
        entry_id = payload.get("entry_id")
        if not isinstance(entry_id, str) or not entry_id.strip():
            raise HIQSPortError("entry_id 必须是有效的 Inbox 条目 ID。")
        normalized_entry_id = entry_id.strip()
        with self.mutation_lock:
            try:
                result = apply_personal_inbox_entry(
                    self.resources_dir,
                    normalized_entry_id,
                    confirmed=True,
                    inbox_repository=self.inbox_repository,
                    information_repository=self.information_repository,
                )
            except (OSError, ValueError, PersonalInboxError) as exc:
                raise HIQSPortError(str(exc)) from exc
        return {
            "entry_id": normalized_entry_id,
            "created_courses": result.created_courses,
            "updated_courses": result.updated_courses,
            "created_items": result.created_items,
            "updated_items": result.updated_items,
        }

    def snapshot(
        self,
        information: InformationStore | None = None,
    ) -> dict[str, Any]:
        try:
            return personal_inbox_snapshot(
                self.resources_dir,
                information=information,
                inbox_repository=self.inbox_repository,
                information_repository=self.information_repository,
            )
        except (OSError, ValueError, PersonalInboxError) as exc:
            raise HIQSPortError(str(exc)) from exc

    def add(self, payload: dict[str, Any]) -> dict[str, Any]:
        title = payload.get("title")
        update = payload.get("update")
        if not isinstance(title, str) or not title.strip():
            raise HIQSPortError("title is required.")
        if not isinstance(update, dict):
            raise HIQSPortError("update must be an InformationUpdate object.")
        note = payload.get("note")
        if note is not None and not isinstance(note, str):
            raise HIQSPortError("note must be a string or null.")
        with self.mutation_lock:
            try:
                entry = add_personal_inbox_entry(
                    self.resources_dir,
                    update,
                    title=title,
                    note=note,
                    repository=self.inbox_repository,
                )
            except (OSError, ValueError, PersonalInboxError) as exc:
                raise HIQSPortError(str(exc)) from exc
        return entry.model_dump(mode="json")

    def get(self, entry_id: str) -> dict[str, Any]:
        try:
            inbox = load_personal_inbox(self.resources_dir, self.inbox_repository)
        except (OSError, ValueError, PersonalInboxError) as exc:
            raise HIQSPortError(str(exc)) from exc
        entry = next(
            (value for value in inbox.entries if value.entry_id == entry_id),
            None,
        )
        if entry is None:
            raise HIQSPortError(f"Personal inbox entry was not found: {entry_id}")
        return entry.model_dump(mode="json")


__all__ = ["PersonalInboxService"]
