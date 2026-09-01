"""Compatibility wrapper for the UI-independent planning application service."""

from __future__ import annotations

from pathlib import Path

from hsas_application.planning import (
    PlanGenerationRequest,
    PlanGenerationResult,
    generate_validated_plan,
)


def generate_plan(
    profile_path: Path | None = None,
    output_path: Path | None = None,
    resources_dir: Path | None = None,
    execution_path: Path | None = None,
    days: int | None = None,
    start: str | None = None,
    fresh: bool = False,
) -> PlanGenerationResult:
    if resources_dir is None:
        raise ValueError("resources_dir is required by the application boundary")
    return generate_validated_plan(
        PlanGenerationRequest(
            resources_dir=resources_dir,
            profile_path=profile_path,
            output_path=output_path,
            execution_path=execution_path,
            days=days,
            start=start,
            fresh=fresh,
        )
    )
