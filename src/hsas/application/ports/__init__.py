"""Application-owned contracts implemented by outer-layer adapters."""

from .gateways import (
    ClassPlannerGateway,
    ClassPlannerSessionResult,
    ClassPlannerSyncResult,
    CourseCatalogEntry,
    CourseCatalogResult,
    CourseGateway,
    MoodleSessionResult,
    SisCourseInfoGateway,
    SisCourseInfoSessionResult,
    SisCourseInfoSyncResult,
    SyncBatchResult,
    SyncCourseResult,
)
from .repositories import ChangeQueueRepository, InformationRepository

__all__ = [
    "ClassPlannerGateway",
    "ClassPlannerSessionResult",
    "ClassPlannerSyncResult",
    "CourseCatalogEntry",
    "CourseCatalogResult",
    "CourseGateway",
    "ChangeQueueRepository",
    "MoodleSessionResult",
    "SisCourseInfoGateway",
    "SisCourseInfoSessionResult",
    "SisCourseInfoSyncResult",
    "InformationRepository",
    "SyncBatchResult",
    "SyncCourseResult",
]
