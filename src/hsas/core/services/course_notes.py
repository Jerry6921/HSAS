"""Local notes runs: immutable inputs, atomic checkpoints and verified exports."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import fcntl
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from hsas.application.course_notes import NotesCheckpoint
from hsas.core.ports import HIQSPortError
from hsas.core.services.materials import MaterialQueryService
from hsas.infrastructure.storage.json_store import atomic_write, read_json, write_json


def _hash(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


@dataclass(slots=True)
class CourseNotesService:
    resources_dir: Path
    materials: MaterialQueryService

    @property
    def root(self) -> Path:
        return self.resources_dir / "course-notes"

    def _path(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise HIQSPortError("Invalid notes run ID.")
        return self.root / run_id / "state.json"

    @contextmanager
    def _lock(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / ".lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _file(self, value: str) -> Path:
        path = (self.resources_dir / value).resolve()
        if not path.is_relative_to(self.resources_dir.resolve()) or not path.is_file():
            raise HIQSPortError("Notes source is missing or outside the resources directory.")
        return path

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirmed") is not True:
            raise HIQSPortError("Creating local notes requires confirmed=true.")
        for key in ("course_id", "scope", "language"):
            if not isinstance(payload.get(key), str) or not payload[key].strip():
                raise HIQSPortError(f"{key} is required.")
        course_id = payload["course_id"]
        manifest = self.materials.manifest([course_id])
        sources: list[dict[str, Any]] = []
        hashes: dict[str, str] = {}
        for document in manifest["documents"]:
            relative_path = document["relative_path"]
            source_id = "file-" + _hash(f"{document['activity_id']}:{relative_path}")[:24]
            source = {
                "source_id": source_id, "title": document["filename"],
                "relative_path": relative_path, "text_relative_path": None,
                "original_sha256": None, "text_sha256": None,
                "inline_text": None, "duplicate_of": None,
                "analysis_status": document["analysis_status"],
                "warnings": list(document["analysis_warnings"]),
            }
            try:
                source["original_sha256"] = _hash(self._file(relative_path).read_bytes())
                if document["text_path"]:
                    text_file = self._file(document["text_path"])
                    source["text_relative_path"] = text_file.relative_to(
                        self.resources_dir.resolve()
                    ).as_posix()
                    source["text_sha256"] = _hash(text_file.read_bytes())
            except (OSError, HIQSPortError) as exc:
                source["warnings"].append(str(exc))
            fingerprint = source["original_sha256"]
            if fingerprint:
                source["duplicate_of"] = hashes.get(fingerprint)
                hashes.setdefault(fingerprint, source_id)
            sources.append(source)
        for index, page in enumerate(manifest["page_content"]):
            # Preserve tables even when their text rendering is incomplete.
            text = page["content_text"]
            if page.get("content_tables"):
                text += "\n\nTables (source data):\n" + json.dumps(
                    page["content_tables"], ensure_ascii=False, default=str
                )
            sources.append({
                "source_id": "page-" + _hash(
                    f"{page['activity_id']}:{page.get('evidence_id', index)}"
                )[:24],
                "title": page["activity_name"], "relative_path": page["relative_path"],
                "text_relative_path": None, "original_sha256": None,
                "text_sha256": _hash(text), "inline_text": text,
                "duplicate_of": None, "analysis_status": "inline",
                "warnings": (
                    [page["evidence_graph"].get("truncation_reason") or "Incomplete activity collection."]
                    if page.get("evidence_graph", {}).get("complete") is False else []
                ),
            })
        if not sources:
            raise HIQSPortError("No archived materials found for this exact course_id.")
        state = {
            "schema_version": "1.0", "run_id": uuid4().hex,
            "course_id": course_id, "scope": payload["scope"],
            "language": payload["language"], "revision": 0,
            "created_at": datetime.now(UTC).isoformat(), "status": "working",
            "status_note": "", "sources": sources, "source_reviews": {},
            "units": [], "artifacts": {}, "questions": [], "limitations": [],
            "publication": None,
        }
        with self._lock():
            write_json(self._path(state["run_id"]), state)
        return self._report(state)

    def get(self, run_id: str | None = None, artifact_id: str | None = None) -> dict[str, Any]:
        try:
            if run_id is None:
                return {"runs": [
                    {key: state[key] for key in (
                        "run_id", "course_id", "scope", "revision", "status", "created_at"
                    )}
                    for path in sorted(self.root.glob("*/state.json"))
                    for state in [read_json(path)]
                ]}
            state = read_json(self._path(run_id))
            report = self._report(state)
            if artifact_id is not None:
                if artifact_id not in state["artifacts"]:
                    raise HIQSPortError("Unknown notes artifact ID.")
                report["artifact"] = state["artifacts"][artifact_id]
            return report
        except (OSError, ValueError, KeyError) as exc:
            raise HIQSPortError(f"Cannot read notes checkpoint: {exc}") from exc

    def read_source(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            state = read_json(self._path(payload["run_id"]))
            source = next((s for s in state["sources"] if s["source_id"] == payload["source_id"]), None)
            if source is None:
                raise HIQSPortError("Unknown notes source ID.")
            offset, limit = payload.get("offset", 0), payload.get("limit", 12000)
            if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 30000:
                raise HIQSPortError("offset must be non-negative; limit must be 1–30000.")
            if source["inline_text"] is not None:
                text = source["inline_text"]
            elif source["text_relative_path"]:
                raw = self._file(source["text_relative_path"]).read_bytes()
                if _hash(raw) != source["text_sha256"]:
                    raise HIQSPortError("Source text changed; start a new run for the new scope.")
                self._verify_original(source)
                text = raw.decode("utf-8")
            else:
                raise HIQSPortError("No extracted text; inspect the original visually/OCR and record limits.")
            if offset > len(text):
                raise HIQSPortError("offset exceeds source length.")
            end = min(offset + limit, len(text))
            return {
                "source_id": source["source_id"], "text": text[offset:end],
                "offset": offset, "next_offset": end, "total_characters": len(text),
                "eof": end >= len(text), "text_sha256": source["text_sha256"],
                "warnings": source["warnings"],
                "reading_status": "Text delivery only; visual completeness needs Agent review.",
            }
        except (OSError, ValueError, KeyError) as exc:
            raise HIQSPortError(f"Cannot read notes source: {exc}") from exc

    def _verify_original(self, source: dict[str, Any]) -> None:
        if source["original_sha256"] and _hash(
            self._file(source["relative_path"]).read_bytes()
        ) != source["original_sha256"]:
            raise HIQSPortError("Original source changed; preserve this run and create a new one.")

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirmed") is not True:
            raise HIQSPortError("Saving local notes requires confirmed=true.")
        try:
            update = NotesCheckpoint.model_validate(payload["update"])
            with self._lock():
                path = self._path(payload["run_id"])
                state = read_json(path)
                revision = payload.get("expected_revision")
                if type(revision) is not int or revision != state["revision"]:
                    raise HIQSPortError("Stale notes revision; fetch the latest checkpoint before retrying.")
                self._check_export_edits(state, update)
                self._merge(state, update)
                blockers = self._completion_blockers(state)
                if update.status == "complete" and blockers:
                    raise HIQSPortError("Notes are incomplete: " + "; ".join(blockers))
                if update.status in {"blocked", "partial"} and not update.status_note:
                    raise HIQSPortError("Partial/blocked checkpoints need a status_note explaining remaining work.")
                state["status"] = update.status
                state["status_note"] = update.status_note
                state["revision"] += 1
                # One atomic document is authoritative. Markdown is a recoverable projection.
                write_json(path, state)
                if read_json(path) != state:
                    raise HIQSPortError("Notes checkpoint readback failed.")
                return self._report(state, export=True)
        except (OSError, ValueError, KeyError, ValidationError) as exc:
            raise HIQSPortError(f"Cannot save notes checkpoint: {exc}") from exc

    def _check_export_edits(self, state: dict[str, Any], update: NotesCheckpoint) -> None:
        directory = self._path(state["run_id"]).parent / "exports" / f"revision-{state['revision']:06d}"
        replacements = {a.artifact_id for a in update.artifacts}
        for artifact_id, artifact in state["artifacts"].items():
            path = directory / f"{artifact_id}.md"
            if path.exists():
                current = path.read_text(encoding="utf-8")
                if current != artifact["content"] and (
                    artifact_id not in replacements
                    or update.reconciled_exports.get(artifact_id) != _hash(current)
                ):
                    raise HIQSPortError(
                        f"User-edited export: {artifact_id}; read and reconcile its content, then "
                        "supply a replacement and its current SHA-256 in reconciled_exports."
                    )

    def _merge(self, state: dict[str, Any], update: NotesCheckpoint) -> None:
        source_ids = {s["source_id"] for s in state["sources"]}
        for values, key in ((update.source_reviews, "source_id"), (update.artifacts, "artifact_id")):
            ids = [getattr(value, key) for value in values]
            if len(ids) != len(set(ids)):
                raise HIQSPortError(f"Duplicate {key} values in checkpoint.")
        for review in update.source_reviews:
            if review.source_id not in source_ids:
                raise HIQSPortError("Review refers to a source outside this run.")
            state["source_reviews"][review.source_id] = review.model_dump(mode="json")
        if update.units is not None:
            ids = [unit.unit_id for unit in update.units]
            if len(ids) != len(set(ids)):
                raise HIQSPortError("Duplicate unit IDs.")
            for unit in update.units:
                if not set(unit.source_ids) <= source_ids:
                    raise HIQSPortError("Unit refers to a source outside this run.")
                if any(p not in ids[:ids.index(unit.unit_id)] for p in unit.prerequisites):
                    raise HIQSPortError("Prerequisites must be earlier units in the plan.")
            state["units"] = [u.model_dump(mode="json") for u in update.units]
        unit_ids = {u["unit_id"] for u in state["units"]}
        for artifact in update.artifacts:
            if artifact.artifact_id == "index":
                raise HIQSPortError("Artifact ID index is reserved for generated navigation.")
            if artifact.kind == "unit" and artifact.artifact_id not in unit_ids:
                raise HIQSPortError("Unit artifacts must use a planned unit ID.")
            state["artifacts"][artifact.artifact_id] = artifact.model_dump(mode="json")
        if update.questions is not None:
            ids = [q.question_id for q in update.questions]
            if len(ids) != len(set(ids)):
                raise HIQSPortError("Duplicate question IDs.")
            state["questions"] = [q.model_dump(mode="json") for q in update.questions]
        # Recheck preserved records too, so a plan edit cannot leave dangling links.
        for artifact in state["artifacts"].values():
            if artifact["kind"] == "unit" and artifact["artifact_id"] not in unit_ids:
                raise HIQSPortError("Plan would orphan an existing unit artifact.")
            for citation in artifact["citations"]:
                if citation["source_id"] not in source_ids:
                    raise HIQSPortError("Artifact cites a source outside this run.")
        for question in state["questions"]:
            if question["source_id"] not in source_ids or not set(question["unit_ids"]) <= unit_ids:
                raise HIQSPortError("Question links must refer to this run's sources and units.")
            answer = question["answer_citation"]
            if answer and answer["source_id"] not in source_ids:
                raise HIQSPortError("Answer citation refers to a source outside this run.")
        if update.limitations is not None:
            state["limitations"] = update.limitations
        if update.publication is not None:
            state["publication"] = update.publication.model_dump(mode="json")

    def _completion_blockers(self, state: dict[str, Any]) -> list[str]:
        blockers = list(state["limitations"])
        included = set()
        for source in state["sources"]:
            source_id = source["source_id"]
            review = state["source_reviews"].get(source_id)
            if review is None:
                blockers.append(f"Unreviewed source: {source_id}")
                continue
            blockers.extend(review["limitations"])
            if review["disposition"] == "excluded":
                continue
            included.add(source_id)
            if review["reading"] != "read" or review["role"] == "unknown":
                blockers.append(f"Reading/role unresolved: {source_id}")
            if review["role"] in {"paper", "quiz"} and not review["question_inventory_complete"]:
                blockers.append(f"Question inventory not reviewed: {source_id}")
            if review["role"] in {"paper", "quiz"} and not any(
                q["source_id"] == source_id for q in state["questions"]
            ) and not review["reason"]:
                blockers.append(f"Empty question inventory needs an explanation: {source_id}")
            try:
                if source["inline_text"] is None and not source["original_sha256"]:
                    blockers.append(f"Original source unavailable at capture: {source_id}")
                self._verify_original(source)
                if source["text_relative_path"] and _hash(
                    self._file(source["text_relative_path"]).read_bytes()
                ) != source["text_sha256"]:
                    blockers.append(f"Source text changed: {source_id}")
            except (OSError, HIQSPortError) as exc:
                blockers.append(f"{source_id}: {exc}")
        if not state["units"]:
            blockers.append("No learning units planned.")
        for unit in state["units"]:
            artifact = state["artifacts"].get(unit["unit_id"])
            if not artifact or artifact["kind"] != "unit":
                blockers.append(f"Missing unit: {unit['unit_id']}")
            elif not set(unit["source_ids"]) <= {c["source_id"] for c in artifact["citations"]}:
                blockers.append(f"Unit citations incomplete: {unit['unit_id']}")
            if not set(unit["source_ids"]) <= included:
                blockers.append(f"Unit uses excluded/unreviewed sources: {unit['unit_id']}")
        covered = {s for u in state["units"] for s in u["source_ids"]}
        for source_id in included:
            role = state["source_reviews"][source_id]["role"]
            if role in {"lecture", "syllabus"} and source_id not in covered:
                blockers.append(f"Lecture/syllabus missing from unit plan: {source_id}")
        kinds = {a["kind"] for a in state["artifacts"].values()}
        for question in state["questions"]:
            if question["source_id"] not in included:
                blockers.append(f"Question uses an excluded/unreviewed source: {question['question_id']}")
            answer = question["answer_citation"]
            if answer and answer["source_id"] not in included:
                blockers.append(f"Answer uses an excluded/unreviewed source: {question['question_id']}")
        for kind in ("overview", "question-map", "review", "coverage"):
            if kind not in kinds:
                blockers.append(f"Missing {kind} artifact.")
        filenames = {f"{key}.md" for key in state["artifacts"]} | {"index.md"}
        for artifact in state["artifacts"].values():
            for target in re.findall(r"\]\(([^)]+)\)", artifact["content"]):
                if "://" not in target and target.split("#")[0].endswith(".md"):
                    if target.split("#")[0] not in filenames:
                        blockers.append(f"Broken note link in {artifact['artifact_id']}: {target}")
        return blockers

    def _report(self, state: dict[str, Any], *, export: bool = False) -> dict[str, Any]:
        report = {key: value for key, value in state.items() if key not in {"sources", "artifacts"}}
        report["sources"] = [
            {key: value for key, value in source.items() if key != "inline_text"}
            for source in state["sources"]
        ]
        report["artifacts"] = [
            {key: value for key, value in artifact.items() if key != "content"}
            | {"sha256": _hash(artifact["content"])}
            for artifact in state["artifacts"].values()
        ]
        report["completion_blockers"] = self._completion_blockers(state)
        report["content_status"] = (
            "stale" if state["status"] == "complete" and report["completion_blockers"] else state["status"]
        )
        report["mastery"] = "not_assessed"
        report["publication_verification"] = "Agent-reported; independent from local content status."
        report["checkpoint_path"] = str(self._path(state["run_id"]).resolve())
        report["local_delivery"] = {"status": "not_exported"}
        if export or state["revision"]:
            try:
                report["local_delivery"] = self._export(state)
            except OSError as exc:
                report["local_delivery"] = {"status": "failed", "error": str(exc), "recoverable": True}
        return report

    def _export(self, state: dict[str, Any]) -> dict[str, Any]:
        # Each revision has stable local links and preserves every previous export.
        directory = self._path(state["run_id"]).parent / "exports" / f"revision-{state['revision']:06d}"
        links = []
        for artifact in state["artifacts"].values():
            filename = f"{artifact['artifact_id']}.md"
            path = directory / filename
            if path.exists() and path.read_text(encoding="utf-8") != artifact["content"]:
                raise OSError(f"User-edited export preserved: {path}. Read and reconcile before retrying.")
            if not path.exists():
                atomic_write(path, artifact["content"])
            if path.read_text(encoding="utf-8") != artifact["content"]:
                raise OSError(f"Artifact readback failed: {artifact['artifact_id']}")
            links.append(f"- [{artifact['title']}]({filename})")
        index = (
            f"# {state['course_id']} course notes\n\n{state['scope']}\n\n"
            f"Content at save: {state['status']}; revision {state['revision']}. Mastery: not assessed.\n\n"
            + "\n".join(links) + "\n"
        )
        path = directory / "index.md"
        if path.exists() and path.read_text(encoding="utf-8") != index:
            raise OSError(f"User-edited index preserved: {path}")
        if not path.exists():
            atomic_write(path, index)
        if path.read_text(encoding="utf-8") != index:
            raise OSError("Notes index readback failed.")
        return {"status": "verified", "index_path": str(path.resolve()), "artifact_count": len(links)}
