"""Query and safely preview locally synchronized course materials."""

from __future__ import annotations

from dataclasses import dataclass, field
import mimetypes
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from hsas.application.ports.repositories import (
    ChangeQueueRepository,
    InformationRepository,
)
from hsas.application.course_context import build_course_question_context
from hsas.application.material_search import (
    EvidenceContentResult,
    list_materials,
    retrieve_evidence_context,
    search_materials,
)
from hsas.core.ports import HIQSPortError
from hsas.domain.courses import activity_evidence_graph, iter_activities, iter_files
from hsas.infrastructure.storage import (
    JsonChangeQueueRepository,
    JsonInformationRepository,
)
from hsas.infrastructure.storage.json_store import read_json


@dataclass(slots=True)
class MaterialQueryService:
    """Expose bounded, read-only access to synchronized source evidence."""

    resources_dir: Path
    information_repository: InformationRepository = field(
        default_factory=JsonInformationRepository,
        repr=False,
    )
    change_repository: ChangeQueueRepository = field(
        default_factory=JsonChangeQueueRepository,
        repr=False,
    )

    def manifest(self, course_ids: list[str] | None = None) -> dict[str, Any]:
        try:
            return list_materials(
                self.resources_dir,
                course_ids=set(course_ids) if course_ids else None,
            )
        except (OSError, ValueError, ValidationError) as exc:
            raise HIQSPortError(str(exc)) from exc

    def search(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = payload.get("query")
        if not isinstance(query, str):
            raise HIQSPortError("query must be a string.")
        course_ids = payload.get("course_ids")
        if course_ids is not None and (
            not isinstance(course_ids, list)
            or not all(isinstance(value, str) for value in course_ids)
        ):
            raise HIQSPortError("course_ids must be a list of strings.")
        try:
            result = search_materials(
                self.resources_dir,
                query,
                course_ids=set(course_ids) if course_ids else None,
                limit=int(payload.get("limit", 6)),
            )
        except (OSError, ValueError, TypeError) as exc:
            raise HIQSPortError(str(exc)) from exc
        return result.model_dump(mode="json")

    def evidence(self, evidence_id: str) -> dict[str, Any]:
        """Resolve one stable evidence node together with its graph neighborhood."""
        if not evidence_id or len(evidence_id) > 500:
            raise HIQSPortError("evidence_id is required and must be bounded.")
        for index in self.change_repository.load_archives(self.resources_dir):
            for activity in iter_activities(index.archive):
                graph = activity_evidence_graph(activity)
                node = next((item for item in graph.nodes if item.evidence_id == evidence_id), None)
                if node is None:
                    continue
                related_ids = {
                    edge.from_id for edge in graph.edges if edge.to_id == evidence_id
                } | {
                    edge.to_id for edge in graph.edges if edge.from_id == evidence_id
                }
                related = [
                    item.model_dump(mode="json")
                    for item in graph.nodes
                    if item.evidence_id in related_ids
                ]
                return {
                    "schema_version": "1.0",
                    "status": "found",
                    "course_id": index.archive.course.course_id,
                    "course_title": index.archive.course.title,
                    "activity_id": activity.module_id,
                    "activity_name": activity.name,
                    "node": node.model_dump(mode="json"),
                    "related_nodes": related,
                    "edges": [edge.model_dump(mode="json") for edge in graph.edges],
                    "graph_complete": graph.complete,
                    "truncation_reason": graph.truncation_reason,
                }
        return {
            "schema_version": "1.0",
            "status": "not_found",
            "evidence_id": evidence_id,
            "reason": "No current course snapshot contains this evidence node.",
        }

    def evidence_content(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Hydrate one selected evidence result without returning unrelated files."""
        evidence_id = payload.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id or len(evidence_id) > 500:
            raise HIQSPortError("evidence_id is required and must be bounded.")
        chunk_index = payload.get("chunk_index")
        if chunk_index is not None and (
            not isinstance(chunk_index, int) or isinstance(chunk_index, bool) or chunk_index < 0
        ):
            raise HIQSPortError("chunk_index must be a non-negative integer or null.")
        context_chunks = payload.get("context_chunks", 1)
        if (
            not isinstance(context_chunks, int)
            or isinstance(context_chunks, bool)
            or context_chunks < 0
            or context_chunks > 3
        ):
            raise HIQSPortError("context_chunks must be between 0 and 3.")
        try:
            chunks = retrieve_evidence_context(
                self.resources_dir,
                evidence_id,
                chunk_index=chunk_index,
                context_chunks=context_chunks,
            )
        except (OSError, ValueError) as exc:
            raise HIQSPortError(str(exc)) from exc
        if not chunks:
            return EvidenceContentResult(
                status="not_found",
                evidence_id=evidence_id,
                chunks=[],
            ).model_dump(mode="json")
        return EvidenceContentResult(
            status="found",
            evidence_id=evidence_id,
            requested_chunk_index=chunk_index,
            context_chunks=context_chunks,
            character_count=sum(len(chunk["text"]) for chunk in chunks),
            chunks=chunks,
        ).model_dump(mode="json")

    def query_course(self, payload: dict[str, Any]) -> dict[str, Any]:
        question = payload.get("question")
        if not isinstance(question, str):
            raise HIQSPortError("question must be a string.")
        course_ids = payload.get("course_ids")
        if course_ids is not None and (
            not isinstance(course_ids, list)
            or not all(isinstance(value, str) for value in course_ids)
        ):
            raise HIQSPortError("course_ids must be a list of strings.")
        information = self._load_information_optional()
        try:
            result = build_course_question_context(
                self.resources_dir,
                question,
                information=information,
                course_ids=set(course_ids) if course_ids else None,
                material_limit=int(payload.get("material_limit", 6)),
                item_limit=int(payload.get("item_limit", 20)),
            )
        except (OSError, ValueError, TypeError) as exc:
            raise HIQSPortError(str(exc)) from exc
        return result.model_dump(mode="json")

    def resolve_file(self, relative_path: str) -> tuple[Path, str]:
        allowed = {
            value["original_relative_path"]
            for value in self._source_inventory().values()
        }
        if relative_path not in allowed:
            raise HIQSPortError("该文件不在当前课程快照中。")
        resources = self.resources_dir.resolve()
        path = (resources / relative_path).resolve()
        if not path.is_relative_to(resources) or not path.is_file():
            raise HIQSPortError("本地课件不存在或路径无效。")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return path, content_type

    def preview(
        self,
        relative_path: str,
        page_numbers: list[int] | None = None,
    ) -> dict[str, Any]:
        source = self._source_inventory().get(relative_path)
        if source is None:
            raise HIQSPortError("该来源不在当前课程快照中。")
        text_path = source.get("text_relative_path")
        preview_text = ""
        truncated = False
        if text_path:
            resolved = self._safe_resource_file(text_path)
            raw_text = resolved.read_text(encoding="utf-8", errors="replace")
            preview_text = _select_source_units(raw_text, page_numbers or [])
            if len(preview_text) > 30000:
                preview_text = preview_text[:30000].rstrip() + "\n\n…预览已截断"
                truncated = True
        content_type = source.get("content_type") or "application/octet-stream"
        preview_kind = (
            "pdf"
            if content_type == "application/pdf"
            else "image"
            if content_type.startswith("image/")
            else "text"
        )
        return {
            "title": source["title"],
            "relative_path": relative_path,
            "original_relative_path": source["original_relative_path"],
            "content_type": content_type,
            "preview_kind": preview_kind,
            "text": preview_text,
            "truncated": truncated,
            "page_numbers": page_numbers or [],
        }

    def _load_information_optional(self):
        path = self.resources_dir / "information.json"
        if not self.information_repository.exists(path):
            return None
        try:
            return self.information_repository.load(path)
        except (OSError, ValueError, ValidationError) as exc:
            raise HIQSPortError(
                f"information.json cannot be loaded: {type(exc).__name__}"
            ) from exc

    def _safe_resource_file(self, relative_path: str) -> Path:
        resources = self.resources_dir.resolve()
        path = (resources / relative_path).resolve()
        if not path.is_relative_to(resources) or not path.is_file():
            raise HIQSPortError("本地来源不存在或路径无效。")
        return path

    def _source_inventory(self) -> dict[str, dict[str, Any]]:
        inventory: dict[str, dict[str, Any]] = {}
        for index in self.change_repository.load_archives(self.resources_dir):
            course_json = (
                index.source_path.resolve()
                .relative_to(self.resources_dir.resolve())
                .as_posix()
                if index.source_path
                else f"courses/{index.archive.course.course_id}/course.json"
            )
            if (self.resources_dir / course_json).is_file():
                inventory[course_json] = {
                    "title": f"{index.archive.course.title} · course.json",
                    "original_relative_path": course_json,
                    "text_relative_path": course_json,
                    "content_type": "application/json",
                }
            for _activity, stored_file in iter_files(index.archive):
                text_path = (
                    stored_file.analysis.extracted_text_path
                    if stored_file.analysis
                    else None
                )
                value = {
                    "title": stored_file.filename,
                    "original_relative_path": stored_file.relative_path,
                    "text_relative_path": text_path,
                    "content_type": stored_file.content_type
                    or mimetypes.guess_type(stored_file.filename)[0]
                    or "application/octet-stream",
                }
                inventory[stored_file.relative_path] = value
                if text_path:
                    inventory[text_path] = value
        manifest_path = self.resources_dir / "sis-course-info" / "latest.json"
        if manifest_path.is_file():
            manifest = read_json(manifest_path)
            courses = manifest.get("courses", []) if isinstance(manifest, dict) else []
            for course in courses:
                if not isinstance(course, dict):
                    continue
                text_path = course.get("text_relative_path")
                html_path = course.get("html_relative_path")
                if not isinstance(text_path, str) or not (
                    self.resources_dir / text_path
                ).is_file():
                    continue
                value = {
                    "title": f"{course.get('course_code', 'Course')} · HKU SIS Course Information",
                    "original_relative_path": text_path,
                    "text_relative_path": text_path,
                    "content_type": "text/plain",
                }
                inventory[text_path] = value
                if isinstance(html_path, str) and (
                    self.resources_dir / html_path
                ).is_file():
                    inventory[html_path] = value
        return inventory


def _select_source_units(text: str, page_numbers: list[int]) -> str:
    if not page_numbers:
        return text
    wanted = set(page_numbers)
    chunks: list[str] = []
    current: list[str] = []
    selected = False
    for line in text.splitlines():
        if line.startswith("--- ") and line.endswith(" ---"):
            if selected and current:
                chunks.append("\n".join(current))
            current = [line]
            selected = any(
                line.startswith(f"--- {label} {number} ")
                or line == f"--- {label} {number} ---"
                for label in ("Page", "Slide", "Speaker notes", "Document part")
                for number in wanted
            )
        elif selected:
            current.append(line)
    if selected and current:
        chunks.append("\n".join(current))
    return "\n\n".join(chunks) or text


__all__ = ["MaterialQueryService"]
