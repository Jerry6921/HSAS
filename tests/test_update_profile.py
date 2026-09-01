import json
from pathlib import Path

import pytest

from hsas.domain.planning.define_profile import StudentProfile
from hsas.application.update_profile import (
    ProfileServiceError,
    apply_profile_patch,
    load_profile,
)
from hsas.infrastructure.storage.persist_data import write_model


def _profile_path(tmp_path: Path) -> Path:
    path = tmp_path / "student_profile.json"
    write_model(path, StudentProfile())
    return path


def test_profile_patch_deep_merges_validates_and_sets_provenance(tmp_path: Path) -> None:
    path = _profile_path(tmp_path)

    profile, changed = apply_profile_patch(
        path,
        {
            "profile_status": "active",
            "identity": {"preferred_name": "Jerry"},
            "availability": {
                "weekly_pattern": [
                    {
                        "day_of_week": "monday",
                        "available_blocks": [
                            {"start": "19:00", "end": "21:00", "capacity": "high"}
                        ],
                    }
                ]
            },
        },
        confirmed=True,
    )

    assert changed == ["availability", "identity", "profile_status"]
    assert profile.identity.preferred_name == "Jerry"
    assert profile.timezone == "Asia/Hong_Kong"
    assert profile.updated_at is not None
    assert profile.provenance.confirmed_by_user is True
    assert profile.provenance.last_confirmed_at is not None
    assert load_profile(path) == profile


def test_profile_patch_requires_confirmation_and_rejects_secrets(tmp_path: Path) -> None:
    path = _profile_path(tmp_path)
    original = path.read_text(encoding="utf-8")

    with pytest.raises(ProfileServiceError, match="explicit user confirmation"):
        apply_profile_patch(path, {"identity": {"preferred_name": "J"}}, confirmed=False)
    with pytest.raises(ProfileServiceError, match="forbidden authentication"):
        apply_profile_patch(
            path,
            {"identity": {"cookie": "secret"}},
            confirmed=True,
        )

    assert path.read_text(encoding="utf-8") == original


def test_invalid_profile_patch_never_replaces_last_good_file(tmp_path: Path) -> None:
    path = _profile_path(tmp_path)
    before = json.loads(path.read_text(encoding="utf-8"))

    with pytest.raises(ProfileServiceError, match="failed validation"):
        apply_profile_patch(
            path,
            {
                "availability": {
                    "weekly_pattern": [
                        {
                            "day_of_week": "monday",
                            "available_blocks": [
                                {"start": "09:00", "end": "11:00"},
                                {"start": "10:00", "end": "12:00"},
                            ],
                        }
                    ]
                }
            },
            confirmed=True,
        )

    assert json.loads(path.read_text(encoding="utf-8")) == before
