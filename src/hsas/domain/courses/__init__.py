"""Normalized course and document domain contracts."""

from .archive_index import ArchiveIndex, iter_activities, iter_files
from .base import StrictModel
from .change_queue import ChangeCheckpoint, PendingChangeBatch
from .models import CourseActivity, CourseArchive
from .evidence import (
    EvidenceEdge,
    EvidenceGraph,
    EvidenceNode,
    LinkedPageEvidence,
    RecursiveCollectionReport,
    activity_evidence_graph,
    linked_page_evidence_id,
)

__all__ = [
    "ArchiveIndex",
    "ChangeCheckpoint",
    "CourseActivity",
    "CourseArchive",
    "PendingChangeBatch",
    "StrictModel",
    "iter_activities",
    "iter_files",
    "EvidenceEdge",
    "EvidenceGraph",
    "EvidenceNode",
    "LinkedPageEvidence",
    "RecursiveCollectionReport",
    "activity_evidence_graph",
    "linked_page_evidence_id",
]
