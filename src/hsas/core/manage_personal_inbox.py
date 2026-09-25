"""Manage staged personal-information updates behind the CORE port."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from math import isfinite
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from hsas.application.manage_inbox import (
    PersonalInboxError,
    add_personal_inbox_entry,
    apply_personal_inbox_entry,
    load_personal_inbox,
    personal_inbox_snapshot,
    preview_personal_inbox_entry,
)
from hsas.application.update_information import load_information
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

    def add_attention_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Stage only explicit student-supplied fields on a complete existing item."""
        item_id = payload.get("item_id")
        fields = payload.get("fields")
        note = payload.get("source_note")
        if not isinstance(item_id, str) or not item_id.strip():
            raise HIQSPortError("请选择需要补充的课程事项。")
        if not isinstance(fields, dict) or not fields:
            raise HIQSPortError("请至少填写一项缺失信息。")
        if set(fields) - {"due_at", "due_time", "submission_method", "submission_link", "weight_percent"}:
            raise HIQSPortError("表单包含不支持的字段。")
        if not isinstance(note, str) or not 3 <= len(note.strip()) <= 500:
            raise HIQSPortError("请填写 3–500 字的信息来源或核对说明。")

        with self.mutation_lock:
            try:
                current = load_information(self.resources_dir / "information.json", self.information_repository)
                item = next((entry for entry in current.items if entry.item_id == item_id.strip()), None)
                if item is None:
                    raise HIQSPortError("课程事项已不存在，请刷新资料后重试。")
                values = item.model_dump(mode="json")
                timezone = ZoneInfo(current.timezone)
                if "due_at" in fields:
                    if item.date_status == "confirmed" and item.due_at is not None:
                        raise HIQSPortError("已确认的截止时间不能通过缺项表单覆盖。")
                    raw = fields["due_at"]
                    if not isinstance(raw, str) or not raw.strip():
                        raise HIQSPortError("请填写有效的截止日期与时间。")
                    try:
                        parsed = datetime.strptime(raw, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone)
                    except ValueError as exc:
                        raise HIQSPortError("截止日期与时间格式无效。") from exc
                    values["due_at"] = parsed.isoformat()
                    values["date_status"] = "tentative"
                if "due_time" in fields:
                    if "due_at" in fields or item.due_on is None or item.due_at is not None:
                        raise HIQSPortError("仅日期已知、时间缺失的事项可以补充截止时间。")
                    raw = fields["due_time"]
                    if not isinstance(raw, str):
                        raise HIQSPortError("请填写有效的截止时间。")
                    try:
                        parsed_time = time.fromisoformat(raw)
                    except ValueError as exc:
                        raise HIQSPortError("截止时间格式无效。") from exc
                    if parsed_time.tzinfo is not None or len(raw) != 5:
                        raise HIQSPortError("截止时间须采用 HH:MM 格式。")
                    values["due_at"] = datetime.combine(item.due_on, parsed_time, timezone).isoformat()
                    values["date_status"] = "tentative"
                if "submission_method" in fields:
                    raw = fields["submission_method"]
                    if item.submission_method or not isinstance(raw, str) or not 1 <= len(raw.strip()) <= 200:
                        raise HIQSPortError("仅可补充缺失的提交方式，长度为 1–200 字。")
                    values["submission_method"] = raw.strip()
                if "submission_link" in fields:
                    raw = fields["submission_link"]
                    parsed_url = urlparse(raw) if isinstance(raw, str) else None
                    if item.links or parsed_url is None or parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                        raise HIQSPortError("仅可补充缺失的有效 HTTP(S) 提交链接。")
                    values["links"] = [*values["links"], {"label": "提交入口（学生手动补充）", "url": raw.strip()}]
                if "weight_percent" in fields:
                    if item.weight_percent is not None or isinstance(fields["weight_percent"], bool):
                        raise HIQSPortError("仅可补充缺失的占分。")
                    try:
                        weight = float(fields["weight_percent"])
                    except (TypeError, ValueError) as exc:
                        raise HIQSPortError("占分必须是 0–100 的数字。") from exc
                    if not isfinite(weight) or not 0 <= weight <= 100:
                        raise HIQSPortError("占分必须是 0–100 的数字。")
                    values["weight_percent"] = weight

                values["sources"] = [*values["sources"], {
                    "source_type": "manual",
                    "title": "学生手动补充（待核对）",
                    "observed_at": datetime.now(UTC).isoformat(),
                    "note": note.strip(),
                }]
                entry = add_personal_inbox_entry(
                    self.resources_dir,
                    {"updated_by": "manual", "items": [values]},
                    title=f"补充待确认事项：{item.title}",
                    note="学生填写的补充信息；核对预览后才可写入课程资料。",
                    repository=self.inbox_repository,
                )
                return preview_personal_inbox_entry(entry, current)
            except (OSError, ValueError, PersonalInboxError) as exc:
                raise HIQSPortError(str(exc)) from exc

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
