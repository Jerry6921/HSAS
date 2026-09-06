"""Validated course-information contracts for AI-authored data."""

from .define_information import (
    CourseRecord,
    InformationItem,
    InformationStore,
    InformationUpdate,
    RelatedMaterial,
    SourceReference,
    WeeklyRecurrence,
)
from .define_inbox import PersonalInbox, PersonalInboxEntry

__all__ = [
    "CourseRecord",
    "InformationItem",
    "InformationStore",
    "InformationUpdate",
    "PersonalInbox",
    "PersonalInboxEntry",
    "RelatedMaterial",
    "SourceReference",
    "WeeklyRecurrence",
]
