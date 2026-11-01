import asyncio
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock
from zipfile import ZipFile

import pytest

from hsas.core import HIQSCore, HIQSPort, HIQSPortError
from hsas.core.services.course_notes import CourseNotesService
from hsas.core.services.materials import MaterialQueryService
from hsas.mcp import build_mcp_server
from hsas.infrastructure.moodle.course_mapper import build_course_archive
from hsas.infrastructure.storage.json_store import write_model
from scripts.generate_notes_contracts import render_notes_contracts
from scripts.package_agent_skills import package_skills


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def setup(tmp_path):
    documents = []
    for name, text in (
        ("lecture", "--- Slide 1 ---\nModel assumptions.\n--- Slide 2 ---\nA non-examined concept."),
        ("quiz", "Q1. Current model.\nQ2. Historical extension with no answer."),
        ("duplicate", "--- Slide 1 ---\nModel assumptions.\n--- Slide 2 ---\nA non-examined concept."),
    ):
        original = tmp_path / f"courses/demo/{name}.pdf"
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(text.encode())
        extracted = original.with_suffix(".txt")
        extracted.write_text(text)
        documents.append({
            "activity_id": name, "relative_path": original.relative_to(tmp_path).as_posix(),
            "filename": original.name, "text_path": str(extracted),
            "analysis_status": "complete", "analysis_warnings": [],
        })
    materials = Mock(spec=MaterialQueryService)
    materials.manifest.return_value = {"documents": documents, "page_content": []}
    service = CourseNotesService(tmp_path, materials)
    run = service.create({"course_id": "demo", "scope": "Current lectures + available historical quiz",
                          "language": "English", "confirmed": True})
    return service, run, documents


def complete_update(run):
    lecture, quiz, duplicate = [s["source_id"] for s in run["sources"]]
    reviews = [
        {"source_id": lecture, "role": "lecture", "reading": "read", "locators": ["Slides 1–2"]},
        {"source_id": quiz, "role": "quiz", "reading": "read", "locators": ["Q1–2"],
         "question_inventory_complete": True},
        {"source_id": duplicate, "role": "lecture", "disposition": "excluded",
         "reason": "Byte-identical lecture; retained provenance through duplicate_of"},
    ]
    artifacts = [{
        "artifact_id": name, "kind": kind, "title": name,
        "content": f"# {name}\n\nModel assumptions and non-examined concept. [Lecture, Slides 1–2]\n",
        "citations": [{"source_id": lecture, "locator": "Slides 1–2"}],
    } for name, kind in (("models", "unit"), ("overview", "overview"),
                         ("questions", "question-map"), ("review", "review"), ("coverage", "coverage"))]
    return {
        "source_reviews": reviews,
        "units": [{"unit_id": "models", "title": "Models", "source_ids": [lecture]}],
        "questions": [
            {"question_id": "quiz-q1", "source_id": quiz, "locator": "Q1",
             "unit_ids": ["models"], "answer_kind": "agent-derived"},
            {"question_id": "quiz-q2", "source_id": quiz, "locator": "Q2",
             "scope": "historical-only", "answer_kind": "unresolved",
             "note": "Outside current lecture scope; no official answer acquired"},
        ],
        "artifacts": artifacts, "status": "complete",
    }


def save(service, run, update, revision=0):
    return service.save({"run_id": run["run_id"], "expected_revision": revision,
                         "update": update, "confirmed": True})


def test_complete_batch_readback_and_resume_without_canonical_changes(setup):
    service, run, _ = setup
    update = complete_update(run)
    first = copy.deepcopy(update)
    first["artifacts"] = first["artifacts"][:1]
    first.update(status="partial", status_note="Remaining: overview, review, question map, coverage")
    checkpoint = save(service, run, first)
    assert checkpoint["status"] == "partial"
    restarted = CourseNotesService(service.resources_dir, service.materials)
    assert restarted.get(run["run_id"])["revision"] == 1
    update.pop("source_reviews")
    update["artifacts"] = update["artifacts"][1:]
    result = save(restarted, run, update, revision=1)
    assert result["completion_blockers"] == []
    assert result["content_status"] == "complete"
    assert result["mastery"] == "not_assessed"
    assert result["local_delivery"]["status"] == "verified"
    assert len(result["artifacts"]) == 5
    index = Path(result["local_delivery"]["index_path"]).read_text()
    assert index.count("](") == 5
    assert restarted.get(run["run_id"], "models")["artifact"]["content"].endswith("Slides 1–2]")
    assert not (service.resources_dir / "information.json").exists()
    assert service.get()["runs"][0]["run_id"] == run["run_id"]


def test_source_pagination_reaches_all_text_and_preserves_hashes(setup):
    service, run, documents = setup
    source = run["sources"][0]
    assert run["sources"][2]["duplicate_of"] == source["source_id"]
    offset, chunks = 0, []
    while True:
        result = service.read_source({"run_id": run["run_id"], "source_id": source["source_id"],
                                      "offset": offset, "limit": 11})
        chunks.append(result["text"])
        if result["eof"]:
            break
        assert result["next_offset"] > offset
        offset = result["next_offset"]
    assert "".join(chunks) == Path(documents[0]["text_path"]).read_text()
    Path(documents[0]["text_path"]).write_text("Changed")
    with pytest.raises(HIQSPortError, match="changed"):
        service.read_source({"run_id": run["run_id"], "source_id": source["source_id"]})


@pytest.mark.parametrize("change,match", [
    (lambda u: u["artifacts"].pop(), "Missing coverage"),
    (lambda u: u["source_reviews"].pop(0), "Unreviewed source"),
    (lambda u: u["source_reviews"][0].update(reading="pending"), "Reading/role unresolved"),
    (lambda u: u["source_reviews"][0].update(reading="limited", limitations=["Slide 2 unreadable"]), "Slide 2 unreadable"),
    (lambda u: u.update(limitations=["Required past paper is missing"]), "Required past paper"),
    (lambda u: u["source_reviews"][1].update(question_inventory_complete=False), "Question inventory"),
    (lambda u: u["questions"][0].update(answer_kind="official"), "Official answers"),
    (lambda u: u["questions"][0].update(unit_ids=["unknown"]), "Question links"),
    (lambda u: u["artifacts"][0]["citations"][0].update(source_id="another-course"), "outside this run"),
    (lambda u: u["artifacts"][1].update(artifact_id="index"), "reserved"),
    (lambda u: u["artifacts"][1].update(content="[Missing](absent.md)"), "Broken note link"),
    (lambda u: u["artifacts"].append(copy.deepcopy(u["artifacts"][0])), "Duplicate artifact_id"),
])
def test_reject_incomplete_or_cross_scope_records_without_replacing_checkpoint(setup, change, match):
    service, run, _ = setup
    before = Path(run["checkpoint_path"]).read_bytes()
    update = complete_update(run)
    change(update)
    with pytest.raises(HIQSPortError, match=match):
        save(service, run, update)
    assert Path(run["checkpoint_path"]).read_bytes() == before


def test_stale_writes_and_parallel_writers_preserve_first_success(setup):
    service, run, _ = setup
    def attempt():
        try:
            return save(service, run, complete_update(run))["revision"]
        except HIQSPortError:
            return "stale"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(results, key=str) == [1, "stale"]


def test_publication_failure_is_separate_and_user_edits_are_preserved(setup):
    service, run, _ = setup
    update = complete_update(run)
    update["publication"] = {"target": "Notion course parent", "status": "failed",
                             "readback_note": "Connection unavailable"}
    result = save(service, run, update)
    assert result["content_status"] == "complete"
    assert result["publication"]["status"] == "failed"
    directory = Path(result["local_delivery"]["index_path"]).parent
    artifact = directory / "models.md"
    artifact.write_text("User annotation")
    report = service.get(run["run_id"])
    assert report["local_delivery"]["status"] == "failed"
    assert artifact.read_text() == "User annotation"
    with pytest.raises(HIQSPortError, match="User-edited export"):
        save(service, run, {"status": "complete"}, revision=1)
    revised = copy.deepcopy(update["artifacts"][0])
    revised["content"] += "\n\nUser annotation"
    report = save(service, run, {"artifacts": [revised], "status": "complete",
                                "reconciled_exports": {"models": hashlib.sha256(b"User annotation").hexdigest()}}, revision=1)
    assert report["local_delivery"]["status"] == "verified"
    assert artifact.read_text() == "User annotation"


def test_source_changes_invalidate_completion_and_path_escape_is_rejected(setup, tmp_path):
    service, run, documents = setup
    save(service, run, complete_update(run))
    Path(documents[0]["text_path"]).write_text("New lecture")
    assert service.get(run["run_id"])["content_status"] == "stale"
    with pytest.raises(HIQSPortError, match="Invalid"):
        service.get("../information")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("Private data")
    symlink = tmp_path / "escape.txt"
    symlink.symlink_to(outside)
    with pytest.raises(HIQSPortError, match="outside"):
        service._file("escape.txt")


def test_export_failure_keeps_checkpoint_and_retry_recovers(setup, monkeypatch):
    service, run, _ = setup
    original = CourseNotesService._export
    def fail(*args):
        raise OSError("disk unavailable")
    monkeypatch.setattr(CourseNotesService, "_export", fail)
    result = save(service, run, complete_update(run))
    assert result["local_delivery"]["status"] == "failed"
    assert Path(run["checkpoint_path"]).exists()
    monkeypatch.setattr(CourseNotesService, "_export", original)
    assert service.get(run["run_id"])["local_delivery"]["status"] == "verified"


def test_atomic_checkpoint_failure_retains_previous_state(setup, monkeypatch):
    service, run, _ = setup
    before = Path(run["checkpoint_path"]).read_bytes()
    def fail(*args):
        raise OSError("disk unavailable")
    monkeypatch.setattr("hsas.core.services.course_notes.write_json", fail)
    with pytest.raises(HIQSPortError, match="disk unavailable"):
        save(service, run, complete_update(run))
    assert Path(run["checkpoint_path"]).read_bytes() == before


def test_source_without_text_can_save_partial_visual_limit_and_not_complete(setup):
    service, run, documents = setup
    service.materials.manifest.return_value["documents"][0]["text_path"] = None
    fresh = service.create({"course_id": "demo", "scope": "Scanned lecture",
                            "language": "English", "confirmed": True})
    source = fresh["sources"][0]["source_id"]
    with pytest.raises(HIQSPortError, match="visually/OCR"):
        service.read_source({"run_id": fresh["run_id"], "source_id": source})
    update = complete_update(fresh)
    update["source_reviews"][0].update(reading="limited", limitations=["Slide 2 diagram cannot be read"])
    update.update(status="partial", status_note="Need readable Slide 2 diagram")
    result = save(service, fresh, update)
    assert result["content_status"] == "partial"
    assert "Slide 2 diagram cannot be read" in result["completion_blockers"]


def test_core_mcp_contract_and_portable_package(tmp_path):
    core = HIQSCore(tmp_path)
    assert isinstance(core, HIQSPort)
    assert core.course_notes_schema()["additionalProperties"] is False
    assert core.course_notes() == {"runs": []}
    server = build_mcp_server(Mock(spec=HIQSPort))
    tools = {t.name for t in asyncio.run(server.list_tools())}
    assert {"create_course_notes", "get_course_notes", "get_course_notes_schema",
            "read_course_note_source", "save_course_notes"} <= tools
    assert json.loads(render_notes_contracts())["checkpoint"] == core.course_notes_schema()
    assert (ROOT / "contracts/course-notes.schema.json").read_text() == render_notes_contracts()
    package = package_skills(tmp_path / "skills.zip")
    with ZipFile(package) as archive:
        assert "hiqs-course-notes/SKILL.md" in archive.namelist()
        assert "hiqs-course-information/SKILL.md" in archive.namelist()
        assert not any("resources" in name or ".env" in name for name in archive.namelist())


def test_real_archive_via_mcp_generates_saved_bundle_without_writing_facts(tmp_path):
    raw = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(raw, course_title="Second Course",
                                   raw_state_path="courses/138907/raw/course-state.json")
    # Only source data is changed: no stubbed Port, inventory or persistence.
    for section in archive.sections:
        section.activities.clear()
    activity_data = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    example = build_course_archive(activity_data, course_title="Example", raw_state_path="raw.json")
    activity = example.sections[0].activities[0]
    activity.files.clear()
    activity.content_text = "# Definitions\nA model specifies assumptions.\n# Cases\nA historical question is not a syllabus."
    activity.linked_pages.clear()
    archive.sections[0].activities.append(activity)
    write_model(tmp_path / "courses/138907/course.json", archive)
    server = build_mcp_server(HIQSCore(tmp_path))

    async def call(name, arguments):
        result = await server.call_tool(name, arguments)
        assert not result.is_error, result
        return result.structured_content

    run = asyncio.run(call("create_course_notes", {
        "course_id": "138907", "scope": "Fixture course, complete archived page",
        "language": "English", "confirmed": True,
    }))
    source = run["sources"][0]["source_id"]
    text = asyncio.run(call("read_course_note_source", {"run_id": run["run_id"], "source_id": source}))
    assert text["eof"] and "historical" in text["text"]
    update = {
        "source_reviews": [{"source_id": source, "role": "lecture", "reading": "read",
                            "locators": ["Definitions", "Cases"]}],
        "units": [{"unit_id": "models", "title": "Models", "source_ids": [source]}],
        "artifacts": [{"artifact_id": key, "kind": kind, "title": title,
                       "content": content, "citations": [{"source_id": source, "locator": "Definitions; Cases"}]}
                      for key, kind, title, content in (
                          ("models", "unit", "Model assumptions", "# Models\n\nA model specifies assumptions. Historical questions need scope review. [Definitions; Cases]"),
                          ("overview", "overview", "Course overview", "# Overview\n\n[Learn models](models.md)"),
                          ("questions", "question-map", "Question map", "# Question map\n\nNo papers in the declared archived-page scope; no official answers claimed."),
                          ("review", "review", "Rapid review", "# Review\n\nIdentify assumptions. [Detailed explanation](models.md)"),
                          ("coverage", "coverage", "Coverage", "# Coverage\n\nBoth Definitions and Cases read and included; learner mastery not assessed."),
                      )],
        "status": "complete",
    }
    result = asyncio.run(call("save_course_notes", {"run_id": run["run_id"], "expected_revision": 0,
                                                    "update": update, "confirmed": True}))
    assert result["content_status"] == "complete"
    directory = Path(result["local_delivery"]["index_path"]).parent
    assert (directory / "models.md").is_file()
    assert "models.md" in (directory / "review.md").read_text()
    assert not (tmp_path / "information.json").exists()
