"""Application-owned contracts implemented by outer-layer adapters."""

from .define_gateways import (
    CourseCatalogEntry,
    CourseCatalogResult,
    CourseGateway,
    MoodleSessionResult,
    SyncBatchResult,
    SyncCourseResult,
)
from .define_repositories import ChangeQueueRepository, InformationRepository

__all__ = [
    "CourseCatalogEntry",
    "CourseCatalogResult",
    "CourseGateway",
    "ChangeQueueRepository",
    "MoodleSessionResult",
    "InformationRepository",
    "SyncBatchResult",
    "SyncCourseResult",
]
