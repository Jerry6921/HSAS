import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hsas.application.update_information import (
    InformationServiceError,
    apply_information_update,
    build_information_template,
)
from hsas.infrastructure.storage import JsonInformationRepository
from hsas.interfaces.run_cli import app


REPOSITORY = JsonInformationRepository()


def _update_payload() -> dict:
    return {
        "schema_version": "1.0",
        "timezone": "Asia/Hong_Kong",
        "updated_by": "ai_agent",
        "courses": [
            {
                "course_id": "COMP1117-2026-S1",
                "code": "COMP1117",
                "title": "Computer Programming",
                "color": "#2563eb",
                "overview": "An introduction to programming.",
                "objectives": ["Write small Python programs"],
            }
        ],
        "items": [
            {
                "item_id": "COMP1117-tutorial-mon",
                "course_id": "COMP1117-2026-S1",
                "title": "Tutorial",
                "category": "tutorial",
                "date_status": "confirmed",
                "recurrence": {
                    "weekdays": [0],
                    "valid_from": "2026-09-01",
                    "valid_until": "2026-11-30",
                    "start_time": "10:30:00",
                    "end_time": "11:20:00",
                },
                "location": "CPD-LG.07",
            },
            {
                "item_id": "COMP1117-assignment-1",
                "course_id": "COMP1117-2026-S1",
                "title": "Assignment 1",
                "category": "assignment",
                "date_status": "confirmed",
                "due_at": "2026-09-20T23:59:00+08:00",
                "weight_percent": 10,
                "assessment_format": "Individual programming assignment",
                "requirements": ["Submit one Python file"],
            },
        ],
    }


def test_information_apply_requires_confirmation_and_writes_atomically(
    tmp_path: Path,
) -> None:
    path = tmp_path / "information.json"

    with pytest.raises(InformationServiceError, match="--confirmed"):
        apply_information_update(
            path,
            _update_payload(),
            confirmed=False,
            repository=REPOSITORY,
        )
    assert not path.exists()

    result = apply_information_update(
        path,
        _update_payload(),
        confirmed=True,
        repository=REPOSITORY,
    )

    assert result.created_courses == 1
    assert result.created_items == 2
    assert REPOSITORY.load(path).items[1].weight_percent == 10
    assert REPOSITORY.load(path).courses[0].objectives == [
        "Write small Python programs"
    ]


def test_information_upsert_preserves_unmentioned_records(tmp_path: Path) -> None:
    path = tmp_path / "information.json"
    apply_information_update(
        path,
        _update_payload(),
        confirmed=True,
        repository=REPOSITORY,
    )
    update = {
        "items": [
            {
                "item_id": "COMP1117-assignment-1",
                "course_id": "COMP1117-2026-S1",
                "title": "Assignment 1 — clarified",
                "category": "assignment",
                "date_status": "tentative",
                "due_at": "2026-09-21T23:59:00+08:00",
                "warnings": ["Moodle and syllabus dates conflict"],
            }
        ]
    }

    result = apply_information_update(
        path,
        update,
        confirmed=True,
        repository=REPOSITORY,
    )
    store = REPOSITORY.load(path)

    assert result.updated_items == 1
    assert len(store.courses) == 1
    assert len(store.items) == 2
    assert store.items[1].title == "Assignment 1 — clarified"
    assert store.items[1].date_status == "tentative"


def test_information_rejects_unknown_course_references(tmp_path: Path) -> None:
    with pytest.raises(InformationServiceError, match="unknown course_id"):
        apply_information_update(
            tmp_path / "information.json",
            {
                "items": [
                    {
                        "item_id": "missing-course-item",
                        "course_id": "MISSING",
                        "title": "Unknown",
                        "category": "other",
                    }
                ]
            },
            confirmed=True,
            repository=REPOSITORY,
        )


def test_information_template_is_schema_valid_and_cli_can_apply_it(tmp_path: Path) -> None:
    assert build_information_template().items[0].recurrence is not None
    update_path = tmp_path / "update.json"
    resources = tmp_path / "resources"

    created = CliRunner().invoke(app, ["information", "template", str(update_path)])
    validated = CliRunner().invoke(app, ["information", "validate", str(update_path)])
    applied = CliRunner().invoke(
        app,
        [
            "--resources",
            str(resources),
            "information",
            "apply",
            str(update_path),
            "--confirmed",
        ],
    )

    assert created.exit_code == 0
    assert validated.exit_code == 0
    assert applied.exit_code == 0
    value = json.loads((resources / "information.json").read_text(encoding="utf-8"))
    assert value["schema_version"] == "1.0"
    assert len(value["items"]) == 2
