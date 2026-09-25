"""Typed, provenance-preserving evidence contracts for Agent retrieval."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, HttpUrl

from .define_models import StrictModel


EvidenceKind = Literal["activity", "html_page", "file", "extracted_text", "table"]
EvidenceStatus = Literal["complete", "partial", "not_accessible", "failed"]


class LinkedPageEvidence(StrictModel):
    """Typed representation of an HTML page discovered through an activity."""

    url: HttpUrl
    depth: int = Field(default=0, ge=0)
    title: str | None = None
    content_text: str = ""
    collected_at: datetime | None = None
    status: EvidenceStatus = "complete"
    warnings: list[str] = Field(default_factory=list)


class RecursiveCollectionReport(StrictModel):
    """Stable report for bounded recursive collection."""

    truncated: bool = False
    max_link_depth: int = Field(default=0, ge=0)
    max_linked_pages: int = Field(default=0, ge=0)
    max_linked_files: int = Field(default=0, ge=0)
    discovered_pages: int = Field(default=0, ge=0)
    discovered_files: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)


class EvidenceNode(StrictModel):
    evidence_id: str
    kind: EvidenceKind
    source_url: HttpUrl | None = None
    local_path: str | None = None
    parent_id: str | None = None
    depth: int = Field(default=0, ge=0)
    status: EvidenceStatus = "complete"
    title: str | None = None
    content_text: str | None = None
    collected_at: datetime | None = None
    warnings: list[str] = Field(default_factory=list)


class EvidenceEdge(StrictModel):
    from_id: str
    to_id: str
    relation: Literal["contains", "links_to", "derived_from"]


class EvidenceGraph(StrictModel):
    nodes: list[EvidenceNode] = Field(default_factory=list)
    edges: list[EvidenceEdge] = Field(default_factory=list)
    complete: bool = True
    truncation_reason: str | None = None


def activity_evidence_graph(activity: object) -> EvidenceGraph:
    """Project a Moodle activity into a stable graph without executing HTML."""
    module_id = str(getattr(activity, "module_id"))
    collected_at = getattr(activity, "downloaded_at", None)
    nodes = [EvidenceNode(
        evidence_id=f"activity:{module_id}",
        kind="activity",
        source_url=getattr(activity, "url", None),
        title=str(getattr(activity, "name", "")),
        collected_at=collected_at,
    )]
    edges: list[EvidenceEdge] = []
    metadata = getattr(activity, "metadata", {})
    typed_pages = getattr(activity, "linked_pages", [])
    pages = typed_pages or (metadata.get("linked_pages", []) if isinstance(metadata, dict) else [])
    for index, raw_page in enumerate(pages if isinstance(pages, list) else []):
        if isinstance(raw_page, LinkedPageEvidence):
            page = raw_page
        elif isinstance(raw_page, dict) and raw_page.get("url"):
            try:
                page = LinkedPageEvidence.model_validate(raw_page)
            except Exception:
                # Preserve malformed legacy evidence as a warning instead of dropping it.
                page = LinkedPageEvidence(
                    url=raw_page["url"],
                    depth=max(0, int(raw_page.get("depth", 0))),
                    title=raw_page.get("title"),
                    content_text=str(raw_page.get("content_text", "")),
                    status="partial",
                    warnings=["legacy linked-page metadata required coercion"],
                )
        else:
            continue
        page_id = f"page:{module_id}:{index}"
        nodes.append(EvidenceNode(
            evidence_id=page_id,
            kind="html_page",
            source_url=page.url,
            parent_id=f"activity:{module_id}",
            depth=page.depth,
            title=page.title,
            content_text=page.content_text,
            status=page.status,
            collected_at=page.collected_at,
            warnings=page.warnings,
        ))
        edges.append(EvidenceEdge(
            from_id=f"activity:{module_id}", to_id=page_id, relation="links_to"
        ))
    for index, stored_file in enumerate(getattr(activity, "files", [])):
        file_id = f"file:{module_id}:{index}"
        nodes.append(EvidenceNode(
            evidence_id=file_id,
            kind="file",
            source_url=getattr(stored_file, "source_url", None),
            local_path=getattr(stored_file, "relative_path", None),
            parent_id=f"activity:{module_id}",
            title=getattr(stored_file, "filename", None),
            collected_at=getattr(stored_file, "downloaded_at", None),
        ))
        edges.append(EvidenceEdge(
            from_id=f"activity:{module_id}", to_id=file_id, relation="contains"
        ))
    report = getattr(activity, "collection_report", None)
    if isinstance(metadata, dict):
        try:
            if not report or report == RecursiveCollectionReport():
                report = RecursiveCollectionReport.model_validate({
                    **(metadata.get("recursive_collection_limits") or {}),
                    "truncated": metadata.get("recursive_collection_truncated", False),
                    "discovered_pages": len(pages) if isinstance(pages, list) else 0,
                    "discovered_files": len(getattr(activity, "files", [])),
                })
        except Exception:
            report = RecursiveCollectionReport(truncated=True, warnings=["invalid collection report"])
    truncated = bool(report and report.truncated)
    return EvidenceGraph(
        nodes=nodes,
        edges=edges,
        complete=not truncated,
        truncation_reason=("recursive collection limit reached" if truncated else None),
    )
