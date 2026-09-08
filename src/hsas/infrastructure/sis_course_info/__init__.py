"""Authenticated HKU SIS course-information collection."""

from .synchronize_course_pages import (
    SisCourseInfoBrowserGateway,
    course_identity,
    sis_course_info_status,
)

__all__ = [
    "SisCourseInfoBrowserGateway",
    "course_identity",
    "sis_course_info_status",
]
