"""Build and acknowledge incremental Moodle-review batches for an AI."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from pathlib import Path

from hsas.application.ports.define_repositories import ChangeQueueRepository
from hsas.domain.courses import ArchiveIndex, iter_files
from hsas.domain.courses.define_courses import StoredFile
from hsas.domain.courses.define_change_queue import (
    ChangeCheckpoint,
    ChangeReference,
    CourseChangeCheckpoint,
    CourseReview,
    PendingChangeBatch,
    ReviewFile,
)
from hsas.domain.courses.detect_changes import CourseChange, CourseChangeSet
from hsas.domain.information import InformationStore


CHECKPOINT_PATH = Path("ai-state/change-checkpoint.json")


class ChangeQueueError(ValueError):
    """A stale, invalid, or unauthorized AI review operation."""


def collect_pending_changes(
    resources_dir: Path,
    repository: ChangeQueueRepository,
    *,
    information: InformationStore | None = None,
    course_ids: set[str] | None = None,
) -> PendingChangeBatch:
    """Return full first-review tasks or changes after each course checkpoint."""
    resources = resources_dir.resolve()
    checkpoint = repository.load_checkpoint(resources / CHECKPOINT_PATH)
    reviews: list[CourseReview] = []
    for index in repository.load_archives(resources):
        archive = index.archive
        course_id = archive.course.course_id
        if course_ids and course_id not in course_ids:
            continue
        processed = checkpoint.courses.get(course_id)
        if processed is None:
            reviews.append(
                CourseReview(
                    course_id=course_id,
                    course_title=archive.course.title,
                    mode="full",
                    acknowledge_through=archive.collected_at,
                    files=_full_review_files(resources, index),
                    affected_information_item_ids=_all_course_items(
                        information,
                        course_id,
                    ),
                )
            )
            continue

        change_sets = [
            change_set
            for change_set in repository.load_change_sets(resources, course_id)
            if processed.processed_through < change_set.current_collected_at
            <= archive.collected_at
        ]
        if not change_sets:
            continue
        changes = [
            _present_change(change_set, change)
            for change_set in change_sets
            for change in change_set.changes
        ]
        reviews.append(
            CourseReview(
                course_id=course_id,
                course_title=archive.course.title,
                mode="incremental",
                acknowledge_through=archive.collected_at,
                changes=changes,
                files=_incremental_review_files(resources, index, changes),
                affected_information_item_ids=_affected_items(information, changes),
            )
        )
    return PendingChangeBatch(resources_dir=str(resources), courses=reviews)


def validate_change_batch(
    resources_dir: Path,
    batch: PendingChangeBatch,
    repository: ChangeQueueRepository,
) -> None:
    """Reject a batch if any course changed after the AI read it."""
    resources = resources_dir.resolve()
    if Path(batch.resources_dir).resolve() != resources:
        raise ChangeQueueError("change batch belongs to a different resources directory")
    archives = {
        index.archive.course.course_id: index.archive
        for index in repository.load_archives(resources)
    }
    seen: set[str] = set()
    for review in batch.courses:
        if review.course_id in seen:
            raise ChangeQueueError(f"duplicate course in change batch: {review.course_id}")
        seen.add(review.course_id)
        archive = archives.get(review.course_id)
        if archive is None:
            raise ChangeQueueError(
                f"course {review.course_id} no longer has a local snapshot"
            )
        if archive.collected_at != review.acknowledge_through:
            raise ChangeQueueError(
                f"course {review.course_id} changed after this batch was generated; "
                "run `hsas changes show` again"
            )


def acknowledge_change_batch(
    resources_dir: Path,
    batch: PendingChangeBatch,
    repository: ChangeQueueRepository,
    *,
    confirmed: bool,
) -> ChangeCheckpoint:
    """Advance checkpoints only for an explicitly reviewed, still-current batch."""
    if not confirmed:
        raise ChangeQueueError("refusing to acknowledge changes without confirmation")
    validate_change_batch(resources_dir, batch, repository)
    resources = resources_dir.resolve()
    path = resources / CHECKPOINT_PATH
    checkpoint = repository.load_checkpoint(path)
    acknowledged_at = datetime.now(UTC)
    courses = dict(checkpoint.courses)
    for review in batch.courses:
        previous = courses.get(review.course_id)
        if previous and previous.processed_through > review.acknowledge_through:
            raise ChangeQueueError(
                f"course {review.course_id} checkpoint is newer than this batch"
            )
        courses[review.course_id] = CourseChangeCheckpoint(
            processed_through=review.acknowledge_through,
            acknowledged_at=acknowledged_at,
        )
    updated = ChangeCheckpoint(updated_at=acknowledged_at, courses=courses)
    repository.save_checkpoint(path, updated)
    return updated


def _present_change(
    change_set: CourseChangeSet,
    change: CourseChange,
) -> ChangeReference:
    return ChangeReference(
        change_set_id=change_set.change_set_id
        or _legacy_change_set_id(change_set),
        detected_at=change_set.detected_at,
        kind=change.kind,
        action=change.action,
        entity_id=change.entity_id,
        title=change.title,
        field=change.field,
        before=change.before,
        after=change.after,
        relative_path=change.relative_path,
        text_path=change.text_path,
        source_url=change.source_url,
    )


def _legacy_change_set_id(change_set: CourseChangeSet) -> str:
    raw = (
        f"{change_set.course_id}:{change_set.current_collected_at.isoformat()}:"
        f"{len(change_set.changes)}"
    )
    return f"legacy:{change_set.course_id}:{hashlib.sha256(raw.encode()).hexdigest()[:20]}"


def _full_review_files(resources: Path, index: ArchiveIndex) -> list[ReviewFile]:
    files = [_course_json_file(resources, index, "baseline")]
    files.extend(
        _review_file(resources, stored_file, "baseline")
        for _activity, stored_file in iter_files(index.archive)
    )
    return files


def _incremental_review_files(
    resources: Path,
    index: ArchiveIndex,
    changes: list[ChangeReference],
) -> list[ReviewFile]:
    files: dict[str, ReviewFile] = {
        "course.json": _course_json_file(resources, index, "modified")
    }
    for change in changes:
        if change.kind != "material" or not change.relative_path:
            continue
        path = _resource_path(resources, change.relative_path)
        files[change.relative_path] = ReviewFile(
            filename=change.title,
            relative_path=change.relative_path,
            local_path=str(path.resolve()),
            text_path=(
                str(_resource_path(resources, change.text_path))
                if change.text_path
                else None
            ),
            exists=path.is_file(),
            change_action=change.action,
        )
    return list(files.values())


def _course_json_file(
    resources: Path,
    index: ArchiveIndex,
    action: str,
) -> ReviewFile:
    path = index.source_path or (
        resources / "courses" / index.archive.course.course_id / "course.json"
    )
    return ReviewFile(
        filename="course.json",
        relative_path=path.resolve().relative_to(resources).as_posix(),
        local_path=str(path.resolve()),
        exists=path.is_file(),
        change_action=action,
    )


def _review_file(
    resources: Path,
    stored_file: StoredFile,
    action: str,
) -> ReviewFile:
    path = _resource_path(resources, stored_file.relative_path)
    analysis = stored_file.analysis
    return ReviewFile(
        filename=stored_file.filename,
        relative_path=stored_file.relative_path,
        local_path=str(path.resolve()),
        text_path=(
            str(_resource_path(resources, analysis.extracted_text_path))
            if analysis and analysis.extracted_text_path
            else None
        ),
        exists=path.is_file(),
        change_action=action,
    )


def _all_course_items(
    information: InformationStore | None,
    course_id: str,
) -> list[str]:
    if information is None:
        return []
    return sorted(
        item.item_id for item in information.items if item.course_id == course_id
    )


def _affected_items(
    information: InformationStore | None,
    changes: list[ChangeReference],
) -> list[str]:
    if information is None:
        return []
    paths = {change.relative_path for change in changes if change.relative_path}
    urls = {change.source_url for change in changes if change.source_url}
    return sorted(
        item.item_id
        for item in information.items
        if any(
            source.relative_path in paths or source.url in urls
            for source in item.sources
        )
    )


def _resource_path(resources: Path, relative_path: str) -> Path:
    path = (resources / relative_path).resolve()
    if path == resources or not path.is_relative_to(resources):
        raise ChangeQueueError(f"unsafe course resource path: {relative_path}")
    return path
