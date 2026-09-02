"""Application-owned contracts implemented by outer-layer adapters."""

from .define_gateways import (
    CourseCatalogEntry,
    CourseCatalogResult,
    CourseGateway,
    MoodleSessionResult,
    SyncBatchResult,
    SyncCourseResult,
)
from .define_repositories import PlanningRepository

__all__ = [
    "CourseCatalogEntry",
    "CourseCatalogResult",
    "CourseGateway",
    "MoodleSessionResult",
    "PlanningRepository",
    "SyncBatchResult",
    "SyncCourseResult",
]
