"""Stable public course-data contracts consumed outside the Collector."""

from .transformation.assessment.schema import AssessmentItem, AssessmentType, SourceReference
from .transformation.common.base_schema import StrictModel
from .transformation.common.course_index import ArchiveIndex, iter_activities, iter_files
from .transformation.common.course_schema import CourseActivity, CourseArchive

__all__ = [
    "ArchiveIndex",
    "AssessmentItem",
    "AssessmentType",
    "CourseActivity",
    "CourseArchive",
    "SourceReference",
    "StrictModel",
    "iter_activities",
    "iter_files",
]
