"""Information contract service used by the HIQS facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from hsas.application.information import (
    InformationServiceError,
    apply_information_update,
    load_information,
    validate_information_update,
    validate_material_coverage,
)
from hsas.domain.information import InformationUpdate
from hsas.infrastructure.storage import JsonInformationRepository


class InformationContractService:
    """Own schema and validation concerns without performing writes."""

    def __init__(self, resources_dir: Path, repository: JsonInformationRepository) -> None:
        self.resources_dir = resources_dir
        self.repository = repository

    def schema(self) -> dict[str, Any]:
        return InformationUpdate.model_json_schema()

    def validate(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_update = payload.get("update", payload)
        try:
            update = validate_information_update(raw_update)
            current = load_information(self.resources_dir / "information.json", self.repository)
            validate_material_coverage(self.resources_dir, current, update)
        except (ValueError, ValidationError, InformationServiceError) as exc:
            raise ValueError(str(exc)) from exc
        return {
            "valid": True,
            "course_count": len(update.courses),
            "item_count": len(update.items),
            "update": update.model_dump(mode="json"),
        }

    def apply(self, payload: dict[str, Any], review_service: Any, mutation_lock: Any) -> dict[str, Any]:
        """Apply a validated update and acknowledge its reviewed source batches."""
        if payload.get("confirmed") is not True:
            raise ValueError("Information apply requires explicit confirmation.")
        raw_update = payload.get("update")
        if not isinstance(raw_update, dict):
            raise ValueError("update must be an InformationUpdate object.")
        review_batches = payload.get("review_batches", {})
        if not isinstance(review_batches, dict):
            raise ValueError("review_batches must be an object.")
        update = validate_information_update(raw_update)
        validated_batches = review_service.validate_review_batches(review_batches)
        if validated_batches and not update.courses and not update.items:
            raise ValueError(
                "An empty update cannot acknowledge review batches; use "
                "acknowledge_changes after confirming no fact change."
            )
        with mutation_lock:
            result = apply_information_update(
                self.resources_dir / "information.json",
                update.model_dump(mode="json"),
                confirmed=True,
                repository=self.repository,
                resources_dir=self.resources_dir,
            )
            checkpoints = review_service.acknowledge_validated_batches(validated_batches)
        return {
            "created_courses": result.created_courses,
            "updated_courses": result.updated_courses,
            "created_items": result.created_items,
            "updated_items": result.updated_items,
            "checkpoints": checkpoints,
        }
