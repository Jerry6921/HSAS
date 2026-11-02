"""Build the read-only information snapshot from canonical facts and source state."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from hsas.application.freshness import build_freshness
from hsas.application.ports.repositories import (
    ChangeQueueRepository,
    InformationRepository,
)
from hsas.core.ports import HIQSPortError
from hsas.core.services.personal_inbox import PersonalInboxService
from hsas.core.services.records import is_user_created_item, matching_archive
from hsas.core.services.reviews import SourceReviewService, pending_summary
from hsas.domain.courses import ArchiveIndex, PendingChangeBatch, iter_activities, iter_files
from hsas.domain.courses.change_queue import CourseReview
from hsas.domain.information import CourseRecord, InformationStore, RecentInformationUpdate
from hsas.domain.information import moodle_source_course_ids
from hsas.domain.information.calendar import build_ics
from hsas.infrastructure.class_planner import class_planner_status
from hsas.infrastructure.documents.ocr import collect_ocr_queue, ocr_capabilities
from hsas.infrastructure.sis.enrollment.client import SisEnrollmentBrowserGateway
from hsas.infrastructure.sis.enrollment.review import collect_sis_enrollment_changes
from hsas.infrastructure.moodle.session_store import load_moodle_session_status
from hsas.infrastructure.sis.course_info import course_identity, sis_course_info_status
from hsas.infrastructure.sis.course_info.review import (
    collect_sis_course_info_changes,
)
from hsas.infrastructure.storage import JsonChangeQueueRepository, JsonInformationRepository
from hsas.infrastructure.storage.json_store import read_json

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SnapshotError = HIQSPortError


@dataclass(slots=True)
class InformationSnapshotService:
    """Compose the validated information read model without mutating course facts."""

    resources_dir: Path
    review_service: SourceReviewService
    personal_inbox_service: PersonalInboxService
    sync_status_provider: Callable[[], dict[str, Any]]
    information_repository: InformationRepository = field(
        default_factory=JsonInformationRepository,
        repr=False,
    )
    change_repository: ChangeQueueRepository = field(
        default_factory=JsonChangeQueueRepository,
        repr=False,
    )

    def information_snapshot(self) -> dict[str, Any]:
        """Return the validated AI-authored database used by the calendar UI."""
        path = self.resources_dir / "information.json"
        if not self.information_repository.exists(path):
            store = InformationStore()
            pending = self.review_service.pending_batch(None)
            courses = self._dashboard_courses(store, pending)
            inbox = self.personal_inbox_service.snapshot(store)
            material_status = self._material_status(store, pending)
            result: dict[str, Any] = {
                "available": False,
                "schema_version": "1.0",
                "timezone": "Asia/Hong_Kong",
                "updated_at": None,
                "updated_by": None,
                "courses": courses,
                "items": [],
                "summary": {
                    "course_count": len(courses),
                    "item_count": 0,
                    "calendar_item_count": 0,
                    "unknown_date_count": 0,
                },
                "pending_review": pending_summary(pending),
                "material_status": material_status,
                "review_closure": self._review_closure(store, pending, material_status),
                "course_reconciliation": self._course_reconciliation(store),
                "personal_inbox": inbox,
                "sis_enrollment": self._sis_enrollment_status(),
                "class_planner": self._class_planner_status(),
                "sis_course_info": self._sis_course_info_status(),
                "moodle_session": load_moodle_session_status(self.resources_dir),
                "updates": _pending_updates(pending),
                "recent_update": self._recent_update(),
                "warnings": [
                    "information.json 尚未建立。请让 AI 阅读本地课程资料并生成更新。"
                ],
            }
            result["freshness"] = build_freshness(result, now=datetime.now(UTC))
            return result
        try:
            store = self.information_repository.load(path)
        except (OSError, ValueError, ValidationError) as exc:
            raise SnapshotError(
                f"information.json 无法通过模型校验：{type(exc).__name__}"
            ) from exc
        calendar_count = sum(
            item.starts_at is not None
            or item.opens_at is not None
            or item.due_at is not None
            or item.due_on is not None
            or item.scheduled_on is not None
            or item.recurrence is not None
            for item in store.items
        )
        payload = store.model_dump(mode="json")
        pending = self.review_service.pending_batch(store)
        courses = self._dashboard_courses(store, pending)
        dashboard_items = []
        for item in payload["items"]:
            value = dict(item)
            value["user_created"] = is_user_created_item(value)
            dashboard_items.append(value)
        inbox = self.personal_inbox_service.snapshot(store)
        material_status = self._material_status(store, pending)
        result = {
            "available": True,
            **payload,
            "courses": courses,
            "items": dashboard_items,
            "summary": {
                "course_count": len(courses),
                "item_count": len(store.items),
                "calendar_item_count": calendar_count,
                "unknown_date_count": sum(
                    item.date_status == "unknown" for item in store.items
                ),
            },
            "pending_review": pending_summary(pending),
            "material_status": material_status,
            "review_closure": self._review_closure(store, pending, material_status),
            "course_reconciliation": self._course_reconciliation(store),
            "personal_inbox": inbox,
            "sis_enrollment": self._sis_enrollment_status(),
            "class_planner": self._class_planner_status(),
            "sis_course_info": self._sis_course_info_status(),
            "moodle_session": load_moodle_session_status(self.resources_dir),
            "updates": _pending_updates(pending),
            "recent_update": self._recent_update(),
            "warnings": [],
        }
        result["freshness"] = build_freshness(result, now=datetime.now(UTC))
        return result

    def _recent_update(self) -> dict[str, Any] | None:
        path = self.resources_dir / "ai-state" / "recent-information-update.json"
        if not path.is_file():
            return None
        try:
            value = read_json(path)
        except (OSError, ValueError):
            return None
        try:
            report = RecentInformationUpdate.model_validate(value)
        except ValidationError:
            return None
        return report.model_dump(mode="json")

    @staticmethod
    def _course_code(*values: object) -> str | None:
        for value in values:
            if not isinstance(value, str):
                continue
            identity = course_identity(value)
            if identity is not None:
                return identity[0]
        return None

    def _course_reconciliation(self, store: InformationStore) -> dict[str, Any]:
        """Compare current enrolment with every local source without merging facts."""
        enrollment = self._sis_enrollment_status()
        sis = self._sis_course_info_status()
        enrolled = {
            code: value
            for value in enrollment.get("courses", [])
            if isinstance(value, dict)
            and (code := self._course_code(value.get("course_code")))
        }
        moodle: dict[str, Any] = {}
        for index in self.change_repository.load_archives(self.resources_dir):
            code = self._course_code(index.archive.course.title)
            if code:
                moodle[code] = index.archive
        sis_courses = {
            code: value
            for value in sis.get("courses", [])
            if isinstance(value, dict)
            and (code := self._course_code(value.get("course_code")))
        }
        planner_courses: dict[str, dict[str, Any]] = {}
        planner_path = self.resources_dir / "class-planner" / "latest.json"
        if planner_path.is_file():
            value = read_json(planner_path)
            payload = value.get("payload", {}) if isinstance(value, dict) else {}
            for row in payload.get("mainTable", []) if isinstance(payload, dict) else []:
                if not isinstance(row, dict):
                    continue
                code = self._course_code(
                    f"{row.get('SUBJECT_AREA', '')}{row.get('CATALOG_NBR', '')}",
                    row.get("COURSE_SUBCLASS"),
                )
                if code:
                    planner_courses[code] = row
        information = {
            code: course
            for course in store.courses
            if (code := self._course_code(course.code, course.title))
        }
        codes = sorted(set(enrolled) | set(moodle) | set(sis_courses) | set(planner_courses) | set(information))
        rows = []
        for code in codes:
            is_current = code in enrolled
            sources = {
                "moodle": code in moodle,
                "sis_course_info": code in sis_courses,
                "class_planner": code in planner_courses,
                "enrollment": code in enrolled,
                "information": code in information,
            }
            missing = [name for name, present in sources.items() if name != "information" and not present]
            pending_write = is_current and not sources["information"]
            legacy = not is_current and any(sources.values())
            state = "legacy" if legacy else "attention" if missing or pending_write else "complete"
            title = (
                (moodle[code].course.title if code in moodle else None)
                or getattr(information.get(code), "title", None)
                or planner_courses.get(code, {}).get("COURSE_TITLE_LONG")
                or enrolled.get(code, {}).get("title")
                or code
            )
            rows.append(
                {
                    "course_code": code,
                    "title": title,
                    "current_enrollment": is_current,
                    "state": state,
                    "sources": sources,
                    "missing_sources": missing,
                    "pending_information_write": pending_write,
                }
            )
        return {
            "rows": rows,
            "counts": {
                "total": len(rows),
                "complete": sum(row["state"] == "complete" for row in rows),
                "attention": sum(row["state"] == "attention" for row in rows),
                "legacy": sum(row["state"] == "legacy" for row in rows),
            },
            "source_labels": {
                "moodle": "Moodle · 最高优先级",
                "sis_course_info": "SIS 课程信息",
                "class_planner": "官方课表",
                "enrollment": "当前注册",
                "information": "本地信息库",
            },
            "source_order": [
                "moodle",
                "sis_course_info",
                "class_planner",
                "enrollment",
                "information",
            ],
            "authority_note": (
                "课程事实发生冲突时采用当前 Moodle 活动、页面、公告或课件支持的值；"
                "SIS 与官方课表只补充 Moodle 未说明的字段。"
            ),
        }

    def _review_closure(
        self,
        store: InformationStore,
        pending: PendingChangeBatch,
        material_status: dict[str, Any],
    ) -> dict[str, Any]:
        counts = material_status["counts"]
        pending_total = int(counts["ai_review"]) + int(counts["ocr"]) + int(counts["google_authorization"])
        sync = self.sync_status_provider()
        retry_tasks = list((sync.get("result") or {}).get("retry_tasks") or [])
        permanent_failures = [
            task for task in retry_tasks if task.get("kind") == "permanent"
        ]
        transient_failures = [
            task for task in retry_tasks if task.get("kind") != "permanent"
        ]
        captured = any((self.resources_dir / name / "latest.json").is_file() for name in ("sis-enrollment", "sis-course-info", "class-planner")) or bool(self.change_repository.load_archives(self.resources_dir))
        stages = [
            {"id": "capture", "label": "来源采集", "state": "complete" if captured else "pending"},
            {"id": "review", "label": "Agent 整理", "state": "complete" if pending_total == 0 else "pending", "count": pending_total},
            {"id": "write", "label": "校验写入", "state": "complete" if store.courses else "pending"},
            {"id": "checkpoint", "label": "Checkpoint", "state": "complete" if int(counts["ai_review"]) == 0 else "pending", "count": int(counts["ai_review"])},
        ]
        return {
            "stages": stages,
            "pending_total": pending_total,
            "retry_tasks": retry_tasks,
            "permanent_failures": permanent_failures,
            "transient_failures": transient_failures,
            # Permanent source failures are recorded and shown, but they are not
            # something a retry can close, so they must not keep closure open.
            "complete": all(stage["state"] == "complete" for stage in stages)
            and not transient_failures,
        }

    def _sis_enrollment_status(self) -> dict[str, Any]:
        try:
            value = SisEnrollmentBrowserGateway(self.resources_dir).status()
            value["review"] = collect_sis_enrollment_changes(self.resources_dir)
            return value
        except (OSError, ValueError) as exc:
            return {
                "available": False,
                "course_count": 0,
                "term": None,
                "login_status": "unknown",
                "review": {"pending_change_count": 0, "changes": []},
                "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            }

    def _class_planner_status(self) -> dict[str, Any]:
        try:
            return class_planner_status(self.resources_dir)
        except (OSError, ValueError) as exc:
            return {
                "available": False,
                "synced_at": None,
                "course_count": 0,
                "meeting_count": 0,
                "term_ids": [],
                "changes": {},
                "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            }

    def _sis_course_info_status(self) -> dict[str, Any]:
        try:
            value = sis_course_info_status(self.resources_dir)
            value["review"] = collect_sis_course_info_changes(self.resources_dir)
            return value
        except (OSError, ValueError) as exc:
            return {
                "available": False,
                "synced_at": None,
                "course_count": 0,
                "changed_course_count": 0,
                "failure_count": 0,
                "login_status": "unknown",
                "review": {"pending_change_count": 0, "changes": []},
                "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            }

    def calendar_ics(self) -> bytes:
        path = self.resources_dir / "information.json"
        if not self.information_repository.exists(path):
            raise SnapshotError("information.json 尚未建立。")
        try:
            return build_ics(self.information_repository.load(path)).encode("utf-8")
        except (OSError, ValueError, ValidationError) as exc:
            raise SnapshotError(f"日历导出失败：{type(exc).__name__}") from exc

    def _dashboard_courses(
        self,
        store: InformationStore,
        pending: PendingChangeBatch,
    ) -> list[dict[str, Any]]:
        archives = {
            index.archive.course.course_id: index
            for index in self.change_repository.load_archives(self.resources_dir)
        }
        pending_by_course = {review.course_id: review for review in pending.courses}
        entries = []
        matched_archive_ids: set[str] = set()
        for record in store.courses:
            indexes = [
                archives[source_id]
                for source_id in moodle_source_course_ids(record)
                if source_id in archives and source_id not in matched_archive_ids
            ]
            if not indexes:
                index = matching_archive(record, archives, matched_archive_ids)
                if index is not None:
                    indexes = [index]
            matched_archive_ids.update(
                index.archive.course.course_id for index in indexes
            )
            entries.append((record.course_id, record, indexes))
        entries.extend(
            (course_id, None, [index])
            for course_id, index in archives.items()
            if course_id not in matched_archive_ids
        )
        result: list[dict[str, Any]] = []
        for course_id, record, indexes in entries:
            archive = indexes[0].archive if indexes else None
            if record is not None:
                value = record.model_dump(mode="json")
            else:
                assert archive is not None
                value = {
                    "course_id": course_id,
                    "code": archive.course.title,
                    "title": archive.course.title,
                    "moodle_course_id": course_id,
                    "semester": None,
                    "color": _course_color(course_id),
                    "overview": None,
                    "objectives": [],
                    "instructors": [],
                    "links": [],
                    "policies": [],
                    "notes": [],
                    "sources": [],
                }
            weighted = [
                item
                for item in store.items
                if item.course_id == course_id and item.weight_percent is not None
            ]
            value["grade_distribution"] = [
                {
                    "item_id": item.item_id,
                    "title": item.title,
                    "category": item.category,
                    "weight_percent": item.weight_percent,
                }
                for item in weighted
            ]
            value["materials"] = _course_materials(
                self.resources_dir,
                indexes,
                [
                    pending_by_course[index.archive.course.course_id]
                    for index in indexes
                    if index.archive.course.course_id in pending_by_course
                ],
                record,
                course_id=value["course_id"],
                course_code=value["code"],
                course_title=value["title"],
            )
            value["moodle"] = (
                {
                    "url": str(archive.course.url),
                    "source_course_ids": [
                        index.archive.course.course_id for index in indexes
                    ],
                    "collected_at": archive.collected_at.isoformat(),
                    "activity_count": archive.stats.activity_count,
                    "downloaded_file_count": archive.stats.downloaded_file_count,
                    "failed_download_count": archive.stats.failed_download_count,
                }
                if archive
                else None
            )
            result.append(value)
        return result

    def _material_status(
        self,
        store: InformationStore,
        pending: PendingChangeBatch,
    ) -> dict[str, Any]:
        ocr_queue = collect_ocr_queue(self.resources_dir)
        google_authorization = []
        archives = self.change_repository.load_archives(self.resources_dir)
        downloaded_file_count = 0
        searchable_file_count = 0
        for index in archives:
            for _activity, stored_file in iter_files(index.archive):
                downloaded_file_count += 1
                if stored_file.analysis and stored_file.analysis.extracted_text_path:
                    searchable_file_count += 1
            for activity in iter_activities(index.archive):
                source_url = str(activity.url) if activity.url else ""
                error = activity.download_error or ""
                if activity.download_status != "external":
                    continue
                if "docs.google.com" not in source_url and "google workspace" not in error.casefold():
                    continue
                google_authorization.append(
                    {
                        "course_id": index.archive.course.course_id,
                        "course_title": index.archive.course.title,
                        "activity_id": activity.module_id,
                        "title": activity.name,
                        "url": source_url or None,
                        "message": error or "Google Workspace access is required",
                    }
                )
        date_unknown = [
            {
                "item_id": item.item_id,
                "course_id": item.course_id,
                "title": item.title,
            }
            for item in store.items
            if item.date_status == "unknown"
        ]
        conflict_markers = ("conflict", "disagree", "inconsistent", "冲突", "不一致")
        source_conflicts = [
            {
                "item_id": item.item_id,
                "course_id": item.course_id,
                "title": item.title,
                "warnings": item.warnings,
            }
            for item in store.items
            if any(
                marker in warning.casefold()
                for warning in item.warnings
                for marker in conflict_markers
            )
        ]
        try:
            sis_pending = collect_sis_course_info_changes(self.resources_dir)[
                "pending_change_count"
            ]
        except (OSError, ValueError):
            sis_pending = 0
        try:
            enrollment_pending = collect_sis_enrollment_changes(self.resources_dir)[
                "pending_change_count"
            ]
        except (OSError, ValueError):
            enrollment_pending = 0
        try:
            planner_pending = int(
                self._class_planner_status().get("review", {}).get("pending_change_count", 0)
            )
        except (OSError, ValueError, TypeError):
            planner_pending = 0
        counts = {
            "course_archives": len(archives),
            "downloaded_files": downloaded_file_count,
            "searchable_files": searchable_file_count,
            "ai_review": pending.pending_change_count + sis_pending + enrollment_pending + planner_pending,
            "ocr": len(ocr_queue),
            "google_authorization": len(google_authorization),
            "date_unknown": len(date_unknown),
            "source_conflicts": len(source_conflicts),
        }
        return {
            "counts": counts,
            "ocr": {"capabilities": ocr_capabilities(), "queue": ocr_queue},
            "google_authorization": google_authorization,
            "date_unknown": date_unknown,
            "source_conflicts": source_conflicts,
        }


def _pending_updates(batch: PendingChangeBatch) -> dict[str, Any]:
    """Shape pending review data for the local update-diff view."""
    return {
        "generated_at": batch.generated_at.isoformat(),
        "courses": [
            {
                "course_id": review.course_id,
                "course_title": review.course_title,
                "information_course_id": review.information_course_id,
                "related_moodle_course_ids": review.related_moodle_course_ids,
                "mode": review.mode,
                "acknowledge_through": review.acknowledge_through.isoformat(),
                "changes": [change.model_dump(mode="json") for change in review.changes],
                "files": [
                    {
                        "filename": file.filename,
                        "relative_path": file.relative_path,
                        "text_path": file.text_path,
                        "exists": file.exists,
                        "change_action": file.change_action,
                    }
                    for file in review.files
                ],
                "affected_information_item_ids": review.affected_information_item_ids,
            }
            for review in batch.courses
        ],
    }

def _course_color(course_id: str) -> str:
    palette = ("#2563eb", "#0f766e", "#7c3aed", "#c2410c", "#be123c", "#0369a1")
    return palette[sum(course_id.encode("utf-8")) % len(palette)]

def _course_materials(
    resources: Path,
    indexes: list[ArchiveIndex],
    reviews: list[CourseReview],
    record: CourseRecord | None,
    *,
    course_id: str,
    course_code: str,
    course_title: str,
) -> dict[str, Any]:
    grouped: dict[str, Any] = {
        "sections": [],
        "unclassified": [],
        "all": [],
    }
    if not indexes:
        return grouped
    if len(indexes) > 1:
        for index in indexes:
            nested = _course_materials(
                resources,
                [index],
                [
                    review
                    for review in reviews
                    if review.course_id == index.archive.course.course_id
                ],
                record,
                course_id=course_id,
                course_code=course_code,
                course_title=course_title,
            )
            grouped["sections"].extend(nested["sections"])
            grouped["unclassified"].extend(nested["unclassified"])
            grouped["all"].extend(nested["all"])
        return grouped
    changed = {
        item.relative_path: item.change_action
        for review in reviews
        for item in review.files
        if item.relative_path != "course.json"
    }
    index = indexes[0]
    archive = index.archive
    section_titles = {
        activity.module_id: section.title
        for section in archive.sections
        for activity in section.activities
    }
    section_titles.update(
        {activity.module_id: "其他" for activity in archive.unassigned_activities}
    )
    materials: list[dict[str, Any]] = []
    for activity in iter_activities(archive):
        if activity.files:
            for stored_file in activity.files:
                path = (resources / stored_file.relative_path).resolve()
                material = {
                    "id": f"{activity.module_id}:{stored_file.source_url}",
                    "title": stored_file.filename,
                    "activity_name": activity.name,
                    "section_title": section_titles.get(activity.module_id),
                    "category": activity.category,
                    "material_type": None,
                    "relative_path": stored_file.relative_path,
                    "source_url": str(stored_file.source_url),
                    "content_type": stored_file.content_type,
                    "size_bytes": stored_file.size_bytes,
                    "downloaded_at": stored_file.downloaded_at.isoformat(),
                    "text_available": bool(
                        stored_file.analysis
                        and stored_file.analysis.extracted_text_path
                    ),
                    "text_path": (
                        stored_file.analysis.extracted_text_path
                        if stored_file.analysis
                        else None
                    ),
                    "exists": path.is_file(),
                    "change_action": changed.get(stored_file.relative_path),
                    "download_status": activity.download_status,
                    "download_error": activity.download_error,
                }
                materials.append(material)
        else:
            material = {
                "id": activity.module_id,
                "title": activity.name,
                "activity_name": activity.name,
                "section_title": section_titles.get(activity.module_id),
                "category": activity.category,
                "material_type": None,
                "relative_path": None,
                "source_url": str(activity.url) if activity.url else None,
                "content_type": None,
                "size_bytes": None,
                "downloaded_at": None,
                "text_available": False,
                "text_path": None,
                "exists": False,
                "change_action": None,
                "download_status": activity.download_status,
                "download_error": activity.download_error,
            }
            materials.append(material)

    unused = {material["id"]: material for material in materials}
    for section in record.material_sections if record is not None else []:
        values: list[dict[str, Any]] = []
        for reference in section.materials:
            matched = _match_archive_material(reference, unused.values())
            if matched is None:
                continue
            unused.pop(matched["id"], None)
            classified = dict(matched)
            classified["material_section"] = section.title
            classified["material_type"] = reference.material_type
            classified["classification_note"] = reference.note
            values.append(classified)
        if values:
            grouped["sections"].append(
                {
                    "title": section.title,
                    "description": section.description,
                    "materials": values,
                }
            )
    grouped["unclassified"] = list(unused.values())
    grouped["all"] = materials
    return grouped

def _match_archive_material(reference: Any, candidates: Any) -> dict[str, Any] | None:
    values = list(candidates)
    if reference.relative_path:
        match = next(
            (
                material
                for material in values
                if material.get("relative_path") == reference.relative_path
            ),
            None,
        )
        if match is not None:
            return match
    if reference.url:
        match = next(
            (
                material
                for material in values
                if material.get("source_url") == reference.url
            ),
            None,
        )
        if match is not None:
            return match
    title = reference.title.strip().casefold()
    title_matches = [
        material
        for material in values
        if str(material.get("title") or "").strip().casefold() == title
    ]
    return title_matches[0] if len(title_matches) == 1 else None

__all__ = ["InformationSnapshotService"]
