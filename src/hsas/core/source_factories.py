"""Construct authenticated institutional-source services at the composition edge."""

from __future__ import annotations

from pathlib import Path

from hsas.application.class_planner_sync import ClassPlannerSynchronizationService
from hsas.application.course_information_sync import SisCourseInfoSynchronizationService
from hsas.application.moodle_sync import CourseSynchronizationService
from hsas.application.unified_course_sync import UnifiedCourseSyncService
from hsas.infrastructure.class_planner import ClassPlannerBrowserGateway
from hsas.infrastructure.sis.enrollment.client import SisEnrollmentBrowserGateway
from hsas.infrastructure.browser.session import BrowserSessionBroker
from hsas.infrastructure.moodle.settings import Settings
from hsas.infrastructure.moodle.gateway import MoodleCourseGateway
from hsas.infrastructure.runtime import hku_portal_profile_dir
from hsas.infrastructure.sis.course_info import SisCourseInfoBrowserGateway


def build_moodle_service(
    resources_dir: Path, *, profile_dir: Path | None = None
) -> CourseSynchronizationService:
    settings = Settings.load(
        output_dir=resources_dir,
        profile_dir=profile_dir or hku_portal_profile_dir(resources_dir),
    )
    return CourseSynchronizationService(MoodleCourseGateway(settings))


def build_unified_course_sync_service(resources_dir: Path) -> UnifiedCourseSyncService:
    settings = Settings.load(
        output_dir=resources_dir,
        profile_dir=hku_portal_profile_dir(resources_dir),
    )
    return UnifiedCourseSyncService(
        BrowserSessionBroker(resources_dir=resources_dir, settings=settings)
    )


def build_class_planner_service(
    resources_dir: Path, *, profile_dir: Path | None = None
) -> ClassPlannerSynchronizationService:
    return ClassPlannerSynchronizationService(
        ClassPlannerBrowserGateway(resources_dir, profile_dir=profile_dir)
    )


def build_sis_course_info_service(
    resources_dir: Path, *, profile_dir: Path | None = None
) -> SisCourseInfoSynchronizationService:
    return SisCourseInfoSynchronizationService(
        SisCourseInfoBrowserGateway(resources_dir, profile_dir=profile_dir)
    )


def build_sis_enrollment_gateway(resources_dir: Path) -> SisEnrollmentBrowserGateway:
    return SisEnrollmentBrowserGateway(resources_dir)
