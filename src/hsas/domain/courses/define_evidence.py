"""Typed, provenance-preserving evidence contracts for Agent retrieval."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, HttpUrl

from .define_models import StrictModel


EvidenceKind = Literal["activity", "html_page", "file", "extracted_text", "table"]
EvidenceStatus = Literal["complete", "partial", "not_accessible", "failed"]


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
    pages = metadata.get("linked_pages", []) if isinstance(metadata, dict) else []
    for index, page in enumerate(pages if isinstance(pages, list) else []):
        if not isinstance(page, dict) or not page.get("url"):
            continue
        page_id = f"page:{module_id}:{index}"
        nodes.append(EvidenceNode(
            evidence_id=page_id,
            kind="html_page",
            source_url=page["url"],
            parent_id=f"activity:{module_id}",
            depth=int(page.get("depth", 0)),
            title=page.get("title"),
            content_text=page.get("content_text"),
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
    truncated = bool(metadata.get("recursive_collection_truncated")) if isinstance(metadata, dict) else False
    return EvidenceGraph(
        nodes=nodes,
        edges=edges,
        complete=not truncated,
        truncation_reason=("recursive collection limit reached" if truncated else None),
    )
