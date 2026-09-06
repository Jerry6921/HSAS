from pathlib import Path

import pytest

from hsas.application.manage_inbox import (
    PersonalInboxError,
    add_personal_inbox_entry,
    apply_personal_inbox_entry,
    load_personal_inbox,
    personal_inbox_snapshot,
)
from hsas.application.update_information import apply_information_update
from hsas.infrastructure.storage import (
    JsonInformationRepository,
    JsonPersonalInboxRepository,
)


INFORMATION_REPOSITORY = JsonInformationRepository()
INBOX_REPOSITORY = JsonPersonalInboxRepository()


def test_personal_inbox_previews_then_applies_a_validated_update(tmp_path: Path) -> None:
    apply_information_update(
        tmp_path / "information.json",
        {
            "courses": [
                {"course_id": "COMP1117-S1", "code": "COMP1117", "title": "Programming"}
            ]
        },
        confirmed=True,
        repository=INFORMATION_REPOSITORY,
    )
    entry = add_personal_inbox_entry(
        tmp_path,
        {
            "items": [
                {
                    "item_id": "COMP1117-personal-tutorial",
                    "course_id": "COMP1117-S1",
                    "title": "My tutorial group",
                    "category": "tutorial",
                    "date_status": "confirmed",
                    "starts_at": "2026-09-08T14:30:00+08:00",
                    "ends_at": "2026-09-08T15:20:00+08:00",
                    "location": "CPD-LG.07",
                    "sources": [
                        {"source_type": "manual", "title": "Student-confirmed AI conversation"}
                    ],
                }
            ]
        },
        title="选择 Tutorial Group 3",
        note="学生在 AI 对话中确认",
        entry_id="personal-tutorial-3",
        repository=INBOX_REPOSITORY,
    )

    snapshot = personal_inbox_snapshot(
        tmp_path,
        inbox_repository=INBOX_REPOSITORY,
        information_repository=INFORMATION_REPOSITORY,
    )
    assert entry.status == "pending"
    assert snapshot["pending_count"] == 1
    assert snapshot["entries"][0]["changes"][0]["action"] == "create"
    assert any(
        field["field"] == "location"
        for field in snapshot["entries"][0]["changes"][0]["fields"]
    )

    with pytest.raises(PersonalInboxError, match="requires confirmation"):
        apply_personal_inbox_entry(
            tmp_path,
            entry.entry_id,
            confirmed=False,
            inbox_repository=INBOX_REPOSITORY,
            information_repository=INFORMATION_REPOSITORY,
        )

    apply_personal_inbox_entry(
        tmp_path,
        entry.entry_id,
        confirmed=True,
        inbox_repository=INBOX_REPOSITORY,
        information_repository=INFORMATION_REPOSITORY,
    )
    information = INFORMATION_REPOSITORY.load(tmp_path / "information.json")
    inbox = load_personal_inbox(tmp_path, INBOX_REPOSITORY)
    assert information.items[0].location == "CPD-LG.07"
    assert inbox.entries[0].status == "applied"
    assert inbox.entries[0].applied_at is not None
