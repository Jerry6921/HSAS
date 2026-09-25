"""Manage source-review batches and their independent checkpoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from hsas.application.change_tracking import (
    ChangeQueueError,
    acknowledge_change_batch,
    collect_pending_changes,
    validate_change_batch,
)
from hsas.application.ports.repositories import (
    ChangeQueueRepository,
    InformationRepository,
)
from hsas.core.ports import HIQSPortError
from hsas.domain.courses import PendingChangeBatch
from hsas.domain.information import InformationStore
from hsas.infrastructure.class_planner.review import (
    ClassPlannerReviewError,
    acknowledge_class_planner_changes,
    collect_class_planner_changes,
    validate_class_planner_batch,
)
from hsas.infrastructure.sis.enrollment.review import (
    SisEnrollmentReviewError,
    acknowledge_sis_enrollment_changes,
    collect_sis_enrollment_changes,
    validate_sis_enrollment_batch,
)
from hsas.infrastructure.sis.course_info.review import (
    SisCourseInfoReviewError,
    acknowledge_sis_course_info_changes,
    collect_sis_course_info_changes,
    validate_sis_course_info_batch,
)
from hsas.infrastructure.storage import (
    JsonChangeQueueRepository,
    JsonInformationRepository,
)


@dataclass(slots=True)
class SourceReviewService:
    """Export, validate and checkpoint Moodle/SIS/Planner review batches."""

    resources_dir: Path
    change_repository: ChangeQueueRepository = field(
        default_factory=JsonChangeQueueRepository,
        repr=False,
    )
    information_repository: InformationRepository = field(
        default_factory=JsonInformationRepository,
        repr=False,
    )

    def pending_changes(self, payload: dict[str, Any]) -> dict[str, Any]:
        source = payload.get("source", "moodle")
        if source == "moodle":
            course_ids = payload.get("course_ids")
            if course_ids is not None and (
                not isinstance(course_ids, list)
                or not all(isinstance(value, str) for value in course_ids)
            ):
                raise HIQSPortError("course_ids must be a list of strings.")
            return self.pending_batch(
                self.load_information_optional(),
                course_ids=set(course_ids or []),
            ).model_dump(mode="json")
        try:
            if source == "class_planner":
                return collect_class_planner_changes(self.resources_dir)
            if source == "sis_course_info":
                return collect_sis_course_info_changes(self.resources_dir)
            if source == "sis_enrollment":
                return collect_sis_enrollment_changes(self.resources_dir)
        except (OSError, ValueError) as exc:
            raise HIQSPortError(str(exc)) from exc
        raise HIQSPortError(f"Unsupported change source: {source}")

    def acknowledge_changes(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirmed") is not True:
            raise HIQSPortError("Change acknowledgement requires confirmation.")
        if payload.get("reviewed_no_information_change") is not True:
            raise HIQSPortError(
                "Use apply_information_update when facts changed; otherwise confirm "
                "reviewed_no_information_change."
            )
        source = payload.get("source", "moodle")
        batch = payload.get("batch")
        if not isinstance(batch, dict):
            raise HIQSPortError("batch must be an exported review object.")
        try:
            validated = self.validate_review_batches({str(source): batch})
            checkpoints = self.acknowledge_validated_batches(validated)
        except (
            OSError,
            ValueError,
            ValidationError,
            ChangeQueueError,
            ClassPlannerReviewError,
            SisCourseInfoReviewError,
            SisEnrollmentReviewError,
        ) as exc:
            raise HIQSPortError(str(exc)) from exc
        return {"source": source, "checkpoint": checkpoints[str(source)]}

    def pending_batch(
        self,
        information: InformationStore | None,
        *,
        course_ids: set[str] | None = None,
    ) -> PendingChangeBatch:
        try:
            return collect_pending_changes(
                self.resources_dir,
                self.change_repository,
                information=information,
                course_ids=course_ids,
            )
        except (OSError, ValueError, ValidationError) as exc:
            raise HIQSPortError(
                f"待处理 Moodle 变化无法读取：{type(exc).__name__}"
            ) from exc

    def load_information_optional(self) -> InformationStore | None:
        path = self.resources_dir / "information.json"
        if not self.information_repository.exists(path):
            return None
        try:
            return self.information_repository.load(path)
        except (OSError, ValueError, ValidationError) as exc:
            raise HIQSPortError(
                f"information.json cannot be loaded: {type(exc).__name__}"
            ) from exc

    def validate_review_batches(self, batches: dict[str, Any]) -> dict[str, Any]:
        validated: dict[str, Any] = {}
        for source, batch in batches.items():
            if source == "moodle":
                value = PendingChangeBatch.model_validate(batch)
                validate_change_batch(self.resources_dir, value, self.change_repository)
            elif source == "class_planner":
                if not isinstance(batch, dict):
                    raise ClassPlannerReviewError("Class Planner batch must be an object")
                validate_class_planner_batch(self.resources_dir, batch)
                value = batch
            elif source == "sis_course_info":
                if not isinstance(batch, dict):
                    raise SisCourseInfoReviewError("HKU SIS batch must be an object")
                validate_sis_course_info_batch(self.resources_dir, batch)
                value = batch
            elif source == "sis_enrollment":
                if not isinstance(batch, dict):
                    raise SisEnrollmentReviewError("Student Center batch must be an object")
                validate_sis_enrollment_batch(self.resources_dir, batch)
                value = batch
            else:
                raise ValueError(f"Unsupported change source: {source}")
            validated[source] = value
        return validated

    def acknowledge_validated_batches(
        self,
        batches: dict[str, Any],
    ) -> dict[str, Any]:
        checkpoints: dict[str, Any] = {}
        for source, batch in batches.items():
            if source == "moodle":
                checkpoint = acknowledge_change_batch(
                    self.resources_dir,
                    batch,
                    self.change_repository,
                    confirmed=True,
                )
                checkpoints[source] = checkpoint.model_dump(mode="json")
            elif source == "class_planner":
                checkpoints[source] = acknowledge_class_planner_changes(
                    self.resources_dir, batch, confirmed=True
                )
            elif source == "sis_course_info":
                checkpoints[source] = acknowledge_sis_course_info_changes(
                    self.resources_dir, batch, confirmed=True
                )
            elif source == "sis_enrollment":
                checkpoints[source] = acknowledge_sis_enrollment_changes(
                    self.resources_dir, batch, confirmed=True
                )
        return checkpoints


__all__ = ["SourceReviewService"]
