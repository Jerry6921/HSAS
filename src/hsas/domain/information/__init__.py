"""Validated course-information contracts for AI-authored data."""

from .models import (
    CourseMaterialSection,
    CourseRecord,
    InformationItem,
    InformationStore,
    InformationUpdate,
    RelatedMaterial,
    RecurrenceException,
    SourceReference,
    WeeklyRecurrence,
    moodle_source_course_ids,
)
from .attention import (
    AttentionAction,
    AttentionEvidence,
    AttentionItem,
    AttentionReason,
    AttentionSeverity,
    AttentionSnapshot,
)
from .inbox import PersonalInbox, PersonalInboxEntry

__all__ = [
    "AttentionAction",
    "AttentionEvidence",
    "AttentionItem",
    "AttentionReason",
    "AttentionSeverity",
    "AttentionSnapshot",
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
    "moodle_source_course_ids",
]
