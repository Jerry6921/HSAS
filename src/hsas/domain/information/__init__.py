"""Validated course-information contracts for AI-authored data."""

from .define_information import (
    CourseMaterialSection,
    CourseRecord,
    InformationItem,
    InformationStore,
    InformationUpdate,
    RelatedMaterial,
    RecurrenceException,
    SourceReference,
    WeeklyRecurrence,
)
from .define_inbox import PersonalInbox, PersonalInboxEntry

__all__ = [
    "CourseRecord",
    "CourseMaterialSection",
    "InformationItem",
    "InformationStore",
    "InformationUpdate",
    "PersonalInbox",
    "PersonalInboxEntry",
    "RelatedMaterial",
    "RecurrenceException",
    "SourceReference",
    "WeeklyRecurrence",
]
