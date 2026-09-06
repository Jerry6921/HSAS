"""Application-owned contracts implemented by outer-layer adapters."""

from .define_gateways import (
    ClassPlannerGateway,
    ClassPlannerSessionResult,
    ClassPlannerSyncResult,
    CourseCatalogEntry,
    CourseCatalogResult,
    CourseGateway,
    MoodleSessionResult,
    SyncBatchResult,
    SyncCourseResult,
)
from .define_repositories import ChangeQueueRepository, InformationRepository

__all__ = [
    "ClassPlannerGateway",
    "ClassPlannerSessionResult",
    "ClassPlannerSyncResult",
    "CourseCatalogEntry",
    "CourseCatalogResult",
    "CourseGateway",
    "ChangeQueueRepository",
    "MoodleSessionResult",
    "InformationRepository",
    "SyncBatchResult",
    "SyncCourseResult",
]
