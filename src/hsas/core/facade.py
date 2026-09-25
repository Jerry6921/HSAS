"""Concrete CORE implementation of the public HIQS port."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Callable

from pydantic import ValidationError

from hsas.application.change_tracking import (
    ChangeQueueError,
)
from hsas.application.information import (
    InformationServiceError,
)
from hsas.infrastructure.sis.enrollment.review import (
    SisEnrollmentReviewError,
    collect_sis_enrollment_changes,
)
from hsas.infrastructure.sis.course_info.review import (
    SisCourseInfoReviewError,
)
from hsas.infrastructure.class_planner.review import (
    ClassPlannerReviewError,
)
from hsas.infrastructure.runtime import get_runtime_paths
from hsas.infrastructure.storage import JsonInformationRepository
from hsas.infrastructure.updates.github import GitHubUpdateService

from hsas.core.ports import HIQSPort, HIQSPortError
from hsas.core.services.records import (
    CourseRecordService,
)
from hsas.core.services.personal_inbox import PersonalInboxService
from hsas.core.services.information import InformationContractService
from hsas.core.container import CoreServices
from hsas.core.services.status import OperationalStatusService
from hsas.core.services.reviews import SourceReviewService
from hsas.core.sync.controller import CourseSyncController
from hsas.core.services.dashboard import DashboardProjectionService, pending_summary
from hsas.core.services.attention import AttentionService
from hsas.core.services.materials import MaterialQueryService
from hsas.core.sync.workflow import CourseSyncWorkflow
from hsas.core.services.runtime import (
    ApplicationLifecycleService,
    LocalEvidenceOperationService,
)
from hsas.core.services.sources import InstitutionalSourceService
from hsas.core.source_factories import (
    build_class_planner_service as _class_planner_service,
    build_moodle_service as _course_service,
    build_sis_course_info_service as _sis_course_info_service,
    build_sis_enrollment_gateway as _sis_enrollment_gateway,
    build_unified_course_sync_service as _unified_course_sync_service,
)

INFORMATION_REPOSITORY = JsonInformationRepository()
PROJECT_ROOT = Path(__file__).resolve().parents[3]


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
    information_contract_service: InformationContractService = field(init=False, repr=False)
    services: CoreServices = field(init=False, repr=False)
    status_service: OperationalStatusService = field(init=False, repr=False)
    lifecycle_service: ApplicationLifecycleService = field(init=False, repr=False)
    evidence_operation_service: LocalEvidenceOperationService = field(init=False, repr=False)
    source_service: InstitutionalSourceService = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.record_service = CourseRecordService(self.resources_dir, self.mutation_lock)
        self.information_contract_service = InformationContractService(
            self.resources_dir, INFORMATION_REPOSITORY
        )
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
        self.status_service = OperationalStatusService(
            self.information_snapshot,
            self.course_sync_status,
        )
        self.lifecycle_service = ApplicationLifecycleService(
            self.update_service, self.mutation_lock, self.course_sync_status
        )
        self.evidence_operation_service = LocalEvidenceOperationService(
            self.resources_dir,
            self.mutation_lock,
            self.course_sync_status,
            _course_service,
        )
        self.source_service = InstitutionalSourceService(
            self.resources_dir,
            self.mutation_lock,
            _course_service,
            _class_planner_service,
            _sis_course_info_service,
            _sis_enrollment_gateway,
            _load_information_if_available,
            self._pending_review_summary,
            collect_sis_enrollment_changes,
        )
        self.services = CoreServices(
            records=self.record_service,
            reviews=self.review_service,
            inbox=self.personal_inbox_service,
            materials=self.material_query_service,
            dashboard=self.dashboard_projection_service,
            sync=self.sync_workflow,
            attention=self.attention_service,
            information=self.information_contract_service,
            status=self.status_service,
            lifecycle=self.lifecycle_service,
            evidence_operations=self.evidence_operation_service,
            sources=self.source_service,
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
        return self.status_service.snapshot()

    def attention_snapshot(self, horizon_days: int = 14) -> dict[str, Any]:
        """Return deterministic, read-only attention signals for agents and UI."""
        try:
            return self.attention_service.snapshot(horizon_days)
        except (TypeError, ValueError) as exc:
            raise DashboardError(str(exc)) from exc

    def information_update_schema(self) -> dict[str, Any]:
        """Return the exact validated write schema accepted by CORE."""
        return self.information_contract_service.schema()

    def validate_information_update(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate an AI-authored update without changing canonical data."""
        try:
            return self.information_contract_service.validate(payload)
        except ValueError as exc:
            raise DashboardError(str(exc)) from exc

    def apply_information_update(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply reviewed facts, then advance supplied source checkpoints."""
        try:
            result = self.information_contract_service.apply(
                payload, self.review_service, self.mutation_lock
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
            **result,
            "information": self.information_snapshot(),
        }

    def application_update_status(self) -> dict[str, object]:
        """Check the fixed public HIQS repository without mutating local files."""
        return self.lifecycle_service.status()

    def apply_application_update(self, payload: dict[str, Any]) -> dict[str, object]:
        """Fast-forward to one explicitly confirmed commit and rebuild the app."""
        return self.lifecycle_service.apply(payload)







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
        return self.evidence_operation_service.verify_moodle_session()



    def process_ocr_queue(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run OCR locally for all currently queued local documents."""
        return self.evidence_operation_service.process_ocr_queue(payload)

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

    def get_evidence(self, evidence_id: str) -> dict[str, Any]:
        return self.material_query_service.evidence(evidence_id)

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

    def moodle_page_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Render a Moodle URL through the same private profile used for sync."""
        return self.evidence_operation_service.moodle_page_preview(payload)

    def _pending_review_summary(self, information) -> dict[str, int]:
        return pending_summary(self.review_service.pending_batch(information))

    def login_moodle(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Open a visible browser and wait for the user to complete SSO/MFA."""
        return self.source_service.login_moodle(payload)

    def synchronize_courses(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Synchronize all courses or one explicitly selected Moodle course."""
        return self.source_service.synchronize_moodle(payload)

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
        return self.source_service.login_class_planner(payload)

    def synchronize_class_planner(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Collect the current authenticated HKU timetable snapshot."""
        return self.source_service.synchronize_class_planner(payload)

    def login_sis_course_info(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Open HKU SIS and wait for user-completed HKU Portal sign-in."""
        return self.source_service.login_sis_course_info(payload)

    def synchronize_sis_course_info(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Collect official pages for the codes discovered in Moodle archives."""
        return self.source_service.synchronize_sis_course_info(payload)

    def synchronize_sis_enrollment(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Capture the current Student Center course list through the shared profile."""
        return self.source_service.synchronize_sis_enrollment(payload)

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
