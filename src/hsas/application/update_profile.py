"""Validated, atomic mutations for user-confirmed Student Profile data."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from pydantic import ValidationError

from hsas.application.ports.define_repositories import PlanningRepository
from hsas.domain.planning.define_profile import StudentProfile


SYSTEM_MANAGED_FIELDS = {
    "schema_version",
    "profile_id",
    "updated_at",
    "provenance",
    "write_policy",
}
DEFAULT_FORBIDDEN_KEYS = {
    "password",
    "mfa_code",
    "sesskey",
    "cookie",
    "access_token",
}


class ProfileServiceError(ValueError):
    """Raised when a requested Profile mutation is unsafe or invalid."""


def load_profile(path: Path, repository: PlanningRepository) -> StudentProfile:
    if not repository.profile_exists(path):
        raise ProfileServiceError(f"profile does not exist: {path}")
    try:
        return repository.load_profile(path)
    except (OSError, ValueError, ValidationError) as exc:
        raise ProfileServiceError(f"invalid Student Profile {path}: {exc}") from exc


def apply_profile_patch(
    path: Path,
    patch: Mapping[str, Any],
    *,
    confirmed: bool,
    repository: PlanningRepository,
) -> tuple[StudentProfile, list[str]]:
    """Deep-merge a confirmed patch, validate the whole Profile, and write it."""
    if not confirmed:
        raise ProfileServiceError("Profile changes require explicit user confirmation")
    if not isinstance(patch, Mapping) or not patch:
        raise ProfileServiceError("Profile patch must be a non-empty JSON object")

    protected = sorted(SYSTEM_MANAGED_FIELDS.intersection(patch))
    if protected:
        raise ProfileServiceError(
            "Profile patch cannot modify system-managed field(s): "
            + ", ".join(protected)
        )

    existing = load_profile(path, repository)
    forbidden = DEFAULT_FORBIDDEN_KEYS | {
        _normalize_key(value) for value in existing.write_policy.never_store_fields
    }
    forbidden_hits = sorted(_find_forbidden_keys(patch, forbidden))
    if forbidden_hits:
        raise ProfileServiceError(
            "Profile patch contains forbidden authentication field(s): "
            + ", ".join(forbidden_hits)
        )

    changed_fields = sorted(str(key) for key in patch)
    candidate = _deep_merge(existing.model_dump(mode="json"), patch)
    now = datetime.now(UTC)
    candidate["updated_at"] = now.isoformat()
    provenance = dict(candidate.get("provenance") or {})
    provenance["last_confirmed_at"] = now.isoformat()
    provenance["confirmed_by_user"] = True
    unresolved = provenance.get("unconfirmed_fields") or []
    provenance["unconfirmed_fields"] = [
        field
        for field in unresolved
        if str(field).split(".", 1)[0] not in changed_fields
    ]
    candidate["provenance"] = provenance

    try:
        profile = StudentProfile.model_validate(candidate)
    except ValidationError as exc:
        raise ProfileServiceError(f"Profile patch failed validation: {exc}") from exc
    repository.save_profile(path, profile)
    return profile, changed_fields


def _deep_merge(base: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    merged = deepcopy(dict(base))
    for key, value in patch.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _normalize_key(value: object) -> str:
    return str(value).strip().casefold().replace("-", "_")


def _find_forbidden_keys(
    value: object,
    forbidden: set[str],
    path: str = "",
) -> set[str]:
    hits: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if _normalize_key(key) in forbidden:
                hits.add(child_path)
            hits.update(_find_forbidden_keys(child, forbidden, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.update(_find_forbidden_keys(child, forbidden, f"{path}[{index}]"))
    return hits
