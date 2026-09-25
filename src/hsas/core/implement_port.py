"""Concrete CORE implementation of the public HIQS port."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Callable

from pydantic import ValidationError

from hsas.application.synchronize_courses import CourseSynchronizationService
from hsas.application.synchronize_unified_courses import UnifiedCourseSyncService
from hsas.application.synchronize_class_planner import (
    ClassPlannerSynchronizationService,
)
from hsas.application.synchronize_course_information import (
    SisCourseInfoSynchronizationService,
)
from hsas.application.manage_changes import (
    ChangeQueueError,
)
from hsas.application.update_information import (
    InformationServiceError,
    apply_information_update as apply_validated_information_update,
    load_information,
    validate_material_coverage,
    validate_information_update as validate_information_payload,
)
from hsas.infrastructure.documents.run_ocr import (
    run_ocr_queue,
)
from hsas.infrastructure.manage_browser_session import BrowserSessionBroker
from hsas.infrastructure.class_planner import (
    ClassPlannerBrowserGateway,
)
from hsas.infrastructure.fetch_sis_enrollment import SisEnrollmentBrowserGateway
from hsas.infrastructure.manage_sis_enrollment import (
    SisEnrollmentReviewError,
    collect_sis_enrollment_changes,
)
from hsas.infrastructure.sis_course_info import (
    SisCourseInfoBrowserGateway,
)
from hsas.infrastructure.sis_course_info.manage_changes import (
    SisCourseInfoReviewError,
)
from hsas.domain.information import (
    InformationUpdate,
)
from hsas.infrastructure.class_planner.manage_changes import (
    ClassPlannerReviewError,
)
from hsas.infrastructure.moodle.load_settings import Settings
from hsas.infrastructure.moodle.record_session import load_moodle_session_status
from hsas.infrastructure.moodle.synchronize_courses import MoodleCourseGateway
from hsas.infrastructure.runtime import get_runtime_paths, hku_portal_profile_dir
from hsas.infrastructure.storage import (
    JsonChangeQueueRepository,
    JsonInformationRepository,
)
from hsas.infrastructure.update_from_github import (
    ApplicationUpdateError,
    GitHubUpdateService,
)

from hsas.core.define_port import HIQSPort, HIQSPortError
from hsas.core.manage_records import (
    CourseRecordService,
)
from hsas.core.manage_personal_inbox import PersonalInboxService
from hsas.core.manage_reviews import SourceReviewService
from hsas.core.orchestrate_sync import CourseSyncController
from hsas.core.build_dashboard import DashboardProjectionService, pending_summary
from hsas.core.build_attention_service import AttentionService
from hsas.core.query_materials import MaterialQueryService
from hsas.core.synchronize_workflow import CourseSyncWorkflow

INFORMATION_REPOSITORY = JsonInformationRepository()
CHANGE_REPOSITORY = JsonChangeQueueRepository()
PROJECT_ROOT = Path(__file__).resolve().parents[3]

class _WorkflowCancelled(RuntimeError):
    pass


def _workflow_stage_label(stage: str) -> str:
    return {
        "enrollment": "课程列表获取",
        "moodle": "Moodle 课程资料",
        "sis_course_info": "SIS 课程信息",
        "timetable": "官方课表",
    }.get(stage, stage)


def _sis_enrollment_gateway(resources_dir: Path) -> SisEnrollmentBrowserGateway:
    return SisEnrollmentBrowserGateway(resources_dir)


DashboardError = HIQSPortError


@dataclass(slots=True)
class HIQSCore:
    resources_dir: Path
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
        repr=False,
    )
    update_service: GitHubUpdateService = field(
        default_factory=lambda: GitHubUpdateService(PROJECT_ROOT), repr=False
    )
    mutation_lock: Lock = field(default_factory=Lock, repr=False)
    sync_controller: CourseSyncController = field(
        default_factory=CourseSyncController,
        repr=False,
    )
    record_service: CourseRecordService = field(init=False, repr=False)
    review_service: SourceReviewService = field(init=False, repr=False)
    personal_inbox_service: PersonalInboxService = field(init=False, repr=False)
    material_query_service: MaterialQueryService = field(init=False, repr=False)
    dashboard_projection_service: DashboardProjectionService = field(
        init=False,
        repr=False,
    )
    sync_workflow: CourseSyncWorkflow = field(init=False, repr=False)
    attention_service: AttentionService = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.record_service = CourseRecordService(self.resources_dir, self.mutation_lock)
        self.review_service = SourceReviewService(self.resources_dir)
        self.personal_inbox_service = PersonalInboxService(
            self.resources_dir,
            self.mutation_lock,
        )
        self.material_query_service = MaterialQueryService(self.resources_dir)
        self.dashboard_projection_service = DashboardProjectionService(
            self.resources_dir,
            self.review_service,
            self.personal_inbox_service,
            self.course_sync_status,
        )
        self.sync_workflow = CourseSyncWorkflow(
            self.resources_dir,
            self.mutation_lock,
            self.sync_controller,
            self.review_service,
            _course_service,
            _class_planner_service,
            _sis_enrollment_gateway,
            _unified_course_sync_service,
        )
        self.attention_service = AttentionService(
            self.information_snapshot,
            self.clock,
        )

    @property
    def sync_job_lock(self) -> Lock:
        return self.sync_controller.lock

    @property
    def sync_cancel_event(self) -> Event:
        return self.sync_controller.cancel_event

    @sync_cancel_event.setter
    def sync_cancel_event(self, value: Event) -> None:
        self.sync_controller.cancel_event = value

    @property
    def sync_thread(self) -> Thread | None:
        return self.sync_controller.thread

    @sync_thread.setter
    def sync_thread(self, value: Thread | None) -> None:
        self.sync_controller.thread = value

    @property
    def sync_job(self) -> dict[str, Any]:
        return self.sync_controller.job

    @sync_job.setter
    def sync_job(self, value: dict[str, Any]) -> None:
        self.sync_controller.job = value

    def information_snapshot(self) -> dict[str, Any]:
        """Return the validated AI-authored database used by the calendar UI."""
        return self.dashboard_projection_service.information_snapshot()

    def status_snapshot(self) -> dict[str, Any]:
        """Return one compact operational status packet for agents and schedulers."""
        snapshot = self.information_snapshot()
        return {
            "available": snapshot["available"],
            "updated_at": snapshot["updated_at"],
            "summary": snapshot["summary"],
            "pending_review": snapshot["pending_review"],
            "material_status": snapshot["material_status"],
            "review_closure": snapshot["review_closure"],
            "personal_inbox": snapshot["personal_inbox"],
            "moodle_session": snapshot["moodle_session"],
            "sis_enrollment": snapshot["sis_enrollment"],
            "class_planner": snapshot["class_planner"],
            "sis_course_info": snapshot["sis_course_info"],
            "sync": self.course_sync_status(),
        }

    def attention_snapshot(self, horizon_days: int = 14) -> dict[str, Any]:
        """Return deterministic, read-only attention signals for agents and UI."""
        try:
            return self.attention_service.snapshot(horizon_days)
        except (TypeError, ValueError) as exc:
            raise DashboardError(str(exc)) from exc

    def information_update_schema(self) -> dict[str, Any]:
        """Return the exact validated write schema accepted by CORE."""
        return InformationUpdate.model_json_schema()

    def validate_information_update(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate an AI-authored update without changing canonical data."""
        raw_update = payload.get("update", payload)
        try:
            update = validate_information_payload(raw_update)
            current = load_information(
                self.resources_dir / "information.json",
                INFORMATION_REPOSITORY,
            )
            validate_material_coverage(self.resources_dir, current, update)
        except (ValueError, ValidationError, InformationServiceError) as exc:
            raise DashboardError(str(exc)) from exc
        return {
            "valid": True,
            "course_count": len(update.courses),
            "item_count": len(update.items),
            "update": update.model_dump(mode="json"),
        }

    def apply_information_update(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply reviewed facts, then advance supplied source checkpoints."""
        if payload.get("confirmed") is not True:
            raise DashboardError("Information apply requires explicit confirmation.")
        raw_update = payload.get("update")
        if not isinstance(raw_update, dict):
            raise DashboardError("update must be an InformationUpdate object.")
        review_batches = payload.get("review_batches", {})
        if not isinstance(review_batches, dict):
            raise DashboardError("review_batches must be an object.")
        try:
            update = validate_information_payload(raw_update)
            validated_batches = self.review_service.validate_review_batches(
                review_batches
            )
            if validated_batches and not update.courses and not update.items:
                raise DashboardError(
                    "An empty update cannot acknowledge review batches; use "
                    "acknowledge_changes after confirming no fact change."
                )
            with self.mutation_lock:
                result = apply_validated_information_update(
                    self.resources_dir / "information.json",
                    update.model_dump(mode="json"),
                    confirmed=True,
                    repository=INFORMATION_REPOSITORY,
                    resources_dir=self.resources_dir,
                )
                checkpoints = self.review_service.acknowledge_validated_batches(
                    validated_batches
                )
        except (
            OSError,
            ValueError,
            ValidationError,
            InformationServiceError,
            ChangeQueueError,
            ClassPlannerReviewError,
            SisCourseInfoReviewError,
            SisEnrollmentReviewError,
        ) as exc:
            raise DashboardError(str(exc)) from exc
        return {
            "created_courses": result.created_courses,
            "updated_courses": result.updated_courses,
            "created_items": result.created_items,
            "updated_items": result.updated_items,
            "checkpoints": checkpoints,
            "information": self.information_snapshot(),
        }

    def application_update_status(self) -> dict[str, object]:
        """Check the fixed public HIQS repository without mutating local files."""
        return self.update_service.status()

    def apply_application_update(self, payload: dict[str, Any]) -> dict[str, object]:
        """Fast-forward to one explicitly confirmed commit and rebuild the app."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认更新 HIQS。")
        target_commit = payload.get("target_commit")
        if not isinstance(target_commit, str):
            raise DashboardError("缺少已确认的更新 commit，请重新检查更新。")
        if self.course_sync_status().get("state") == "running":
            raise DashboardError("课程同步正在运行，请完成或取消同步后再更新。")
        with self.mutation_lock:
            try:
                return self.update_service.apply(
                    confirmed=True,
                    target_commit=target_commit,
                )
            except ApplicationUpdateError as exc:
                raise DashboardError(str(exc)) from exc







    def calendar_ics(self) -> bytes:
        return self.dashboard_projection_service.calendar_ics()

    def add_course(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.record_service.add_course(payload)

    def delete_course(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.record_service.delete_course(payload)

    def delete_courses(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.record_service.delete_courses(payload)

    def add_calendar_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.record_service.add_calendar_event(payload)

    def delete_calendar_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.record_service.delete_calendar_event(payload)


    def verify_moodle_session(self) -> dict[str, Any]:
        """Verify the saved Moodle browser session without changing course data."""
        if not self.mutation_lock.acquire(blocking=False):
            return {
                **load_moodle_session_status(self.resources_dir),
                "verification_deferred": True,
            }
        try:
            result = _course_service(self.resources_dir).check_login_status()
        except Exception as exc:
            return {
                **load_moodle_session_status(self.resources_dir),
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
            }
        finally:
            self.mutation_lock.release()
        return {
            **load_moodle_session_status(self.resources_dir),
            "error": result.error,
            "verification_deferred": False,
        }



    def process_ocr_queue(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run OCR locally for all currently queued local documents."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认开始本地批量 OCR。")
        with self.mutation_lock:
            try:
                return run_ocr_queue(self.resources_dir)
            except (OSError, ValueError) as exc:
                raise DashboardError(f"OCR 处理失败：{type(exc).__name__}: {str(exc)[:300]}") from exc

    def apply_personal_inbox(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply one explicitly confirmed personal-information draft."""
        return self.personal_inbox_service.apply(payload)

    def personal_inbox_snapshot(self) -> dict[str, Any]:
        """Return pending personal drafts and their field-level previews."""
        return self.personal_inbox_service.snapshot()

    def add_personal_inbox(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Stage a validated personal update without applying it."""
        return self.personal_inbox_service.add(payload)

    def add_attention_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Stage student-entered missing details for later inbox review."""
        return self.personal_inbox_service.add_attention_draft(payload)

    def personal_inbox_entry(self, entry_id: str) -> dict[str, Any]:
        """Return one complete validated personal draft."""
        return self.personal_inbox_service.get(entry_id)

    def materials_manifest(self, course_ids: list[str] | None = None) -> dict[str, Any]:
        """List local source files and extracted-text sidecars."""
        return self.material_query_service.manifest(course_ids)

    def search_materials(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return page-aware local lexical evidence."""
        return self.material_query_service.search(payload)

    def query_course(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Build a cited RAG packet from structured facts and local materials."""
        return self.material_query_service.query_course(payload)

    def pending_changes(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return an exact review batch for one canonical source."""
        return self.review_service.pending_changes(payload)

    def acknowledge_changes(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Advance one source checkpoint after an explicit no-change review."""
        return self.review_service.acknowledge_changes(payload)

    def material_file(self, relative_path: str) -> tuple[Path, str]:
        """Resolve only a file referenced by the latest validated course snapshots."""
        return self.material_query_service.resolve_file(relative_path)

    def source_preview(
        self,
        relative_path: str,
        page_numbers: list[int] | None = None,
    ) -> dict[str, Any]:
        """Return a bounded preview for a source in the current Moodle archive."""
        return self.material_query_service.preview(relative_path, page_numbers)

    def _pending_review_summary(self, information) -> dict[str, int]:
        return pending_summary(self.review_service.pending_batch(information))

    def login_moodle(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Open a visible browser and wait for the user to complete SSO/MFA."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认打开 Moodle 登录窗口。")
        with self.mutation_lock:
            try:
                result = _course_service(self.resources_dir).login_until_ready()
            except Exception as exc:
                raise DashboardError(
                    f"Moodle 登录未完成：{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {
            "status": result.status,
            "checked_at": result.checked_at,
            "available_course_count": result.available_course_count,
            "error": result.error,
        }

    def synchronize_courses(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Synchronize all courses or one explicitly selected Moodle course."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认开始同步 Moodle 课程资料。")
        course = payload.get("course")
        if course is not None and (not isinstance(course, str) or not course.strip()):
            raise DashboardError("course 必须是 Moodle course ID 或同源 URL。")
        course = course.strip() if isinstance(course, str) else None
        with self.mutation_lock:
            try:
                service = _course_service(self.resources_dir)
                if course:
                    result = service.sync_course(course)
                    return {
                        "scope": "single",
                        "discovered_course_count": 1,
                        "succeeded_course_count": 1,
                        "failed_course_count": 0,
                        "course_id": result.course_id,
                        "report_path": str(result.output_path),
                        "pending_review": self._pending_review_summary(
                            _load_information_if_available(self.resources_dir)
                        ),
                    }
                result = service.sync_all()
            except Exception as exc:
                raise DashboardError(
                    f"Moodle 同步失败，上一份有效资料已保留："
                    f"{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {
            "scope": "all",
            "discovered_course_count": result.discovered_course_count,
            "succeeded_course_count": len(result.succeeded_course_ids),
            "failed_course_count": len(result.failures),
            "course_id": None,
            "report_path": str(result.report_path),
            "pending_review": self._pending_review_summary(
                _load_information_if_available(self.resources_dir)
            ),
        }

    def start_course_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.sync_workflow.start_course_sync(payload)

    def retry_failed_course_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.sync_workflow.retry_failed_course_sync(payload)

    def course_sync_status(self) -> dict[str, Any]:
        return self.sync_workflow.course_sync_status()


    def cancel_course_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.sync_workflow.cancel_course_sync(payload)


    def login_class_planner(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Open Class Planner and wait for user-completed HKU Portal sign-in."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认打开 HKU Portal 登录窗口。")
        with self.mutation_lock:
            try:
                result = _class_planner_service(self.resources_dir).login_until_ready()
            except Exception as exc:
                raise DashboardError(
                    f"Class Planner 登录未完成：{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {
            "status": result.status,
            "checked_at": result.checked_at,
            "course_count": result.course_count,
            "term_ids": list(result.term_ids),
            "error": result.error,
        }

    def synchronize_class_planner(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Collect the current authenticated HKU timetable snapshot."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认同步 HKU Class Planner 课表。")
        with self.mutation_lock:
            try:
                result = _class_planner_service(self.resources_dir).sync()
            except Exception as exc:
                raise DashboardError(
                    f"Class Planner 同步失败，上一份快照已保留："
                    f"{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {
            "status": result.status,
            "synced_at": result.synced_at,
            "course_count": result.course_count,
            "meeting_count": result.meeting_count,
            "term_ids": list(result.term_ids),
            "changed": result.changed,
            "added_course_count": len(result.added_course_ids),
            "modified_course_count": len(result.modified_course_ids),
            "removed_course_count": len(result.removed_course_ids),
        }

    def login_sis_course_info(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Open HKU SIS and wait for user-completed HKU Portal sign-in."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认打开 HKU SIS 登录窗口。")
        with self.mutation_lock:
            try:
                result = _sis_course_info_service(self.resources_dir).login_until_ready()
            except Exception as exc:
                raise DashboardError(
                    f"HKU SIS 登录未完成：{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {
            "status": result.status,
            "checked_at": result.checked_at,
            "available_course_count": result.available_course_count,
            "error": result.error,
        }

    def synchronize_sis_course_info(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Collect official pages for the codes discovered in Moodle archives."""
        if payload.get("confirmed") is not True:
            raise DashboardError("请先确认同步 HKU SIS 课程信息。")
        had_snapshot = (self.resources_dir / "sis-course-info" / "latest.json").is_file()
        with self.mutation_lock:
            try:
                result = _sis_course_info_service(self.resources_dir).sync()
            except Exception as exc:
                raise DashboardError(
                    f"HKU SIS 课程信息同步失败，"
                    f"{'上一份快照已保留' if had_snapshot else '尚未写入任何 SIS 课程信息'}："
                    f"{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {
            "status": result.status,
            "synced_at": result.synced_at,
            "discovered_course_count": result.discovered_course_count,
            "succeeded_course_count": len(result.succeeded_course_codes),
            "unchanged_course_count": len(result.unchanged_course_codes),
            "skipped_course_count": len(result.skipped_course_titles),
            "failed_course_count": len(result.failures),
        }

    def synchronize_sis_enrollment(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Capture the current Student Center course list through the shared profile."""
        if payload.get("confirmed") is not True:
            raise DashboardError("Please confirm Student Center synchronization.")
        with self.mutation_lock:
            try:
                result = _sis_enrollment_gateway(self.resources_dir).sync(auto_login=True)
            except Exception as exc:
                raise DashboardError(
                    "Student Center synchronization failed; the previous snapshot was "
                    f"retained: {type(exc).__name__}: {str(exc)[:300]}"
                ) from exc
        return {
            "status": "synced",
            "course_count": len(result.get("courses", [])),
            "term": result.get("term"),
            "review": collect_sis_enrollment_changes(self.resources_dir),
        }

def _course_service(
    resources_dir: Path,
    *,
    profile_dir: Path | None = None,
) -> CourseSynchronizationService:
    settings = Settings.load(
        output_dir=resources_dir,
        profile_dir=profile_dir or hku_portal_profile_dir(resources_dir),
    )
    return CourseSynchronizationService(MoodleCourseGateway(settings))


def _unified_course_sync_service(resources_dir: Path) -> UnifiedCourseSyncService:
    settings = Settings.load(
        output_dir=resources_dir,
        profile_dir=hku_portal_profile_dir(resources_dir),
    )
    return UnifiedCourseSyncService(
        BrowserSessionBroker(resources_dir=resources_dir, settings=settings)
    )


def _class_planner_service(
    resources_dir: Path,
    *,
    profile_dir: Path | None = None,
) -> ClassPlannerSynchronizationService:
    return ClassPlannerSynchronizationService(
        ClassPlannerBrowserGateway(resources_dir, profile_dir=profile_dir)
    )


def _sis_course_info_service(
    resources_dir: Path,
    *,
    profile_dir: Path | None = None,
) -> SisCourseInfoSynchronizationService:
    return SisCourseInfoSynchronizationService(
        SisCourseInfoBrowserGateway(resources_dir, profile_dir=profile_dir)
    )


def _load_information_if_available(resources_dir: Path):
    path = resources_dir / "information.json"
    return INFORMATION_REPOSITORY.load(path) if INFORMATION_REPOSITORY.exists(path) else None























DashboardService = HIQSCore


def build_port(resources_dir: Path | None = None) -> HIQSPort:
    """Build the production CORE implementation behind the stable port."""
    resources = (
        get_runtime_paths().create().resources_dir
        if resources_dir is None
        else resources_dir
    )
    return HIQSCore(resources_dir=resources)
