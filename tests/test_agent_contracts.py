import json
from pathlib import Path

from hsas.application.course_context import CourseQuestionContext
from hsas.application.material_search import EvidenceContentResult, MaterialSearchResult
from scripts.generate_agent_contracts import contract_document, render_contract_document


ROOT = Path(__file__).parents[1]


def test_committed_agent_contract_snapshot_is_current() -> None:
    snapshot = ROOT / "contracts" / "agent-evidence.schema.json"
    assert snapshot.read_text(encoding="utf-8") == render_contract_document()


def test_agent_contracts_have_an_explicit_compatible_version() -> None:
    document = contract_document()
    assert document["schema_version"] == "1.0"
    assert set(document["contracts"]) == {
        "CourseQuestionContext",
        "EvidenceContentResult",
        "MaterialSearchResult",
    }
    assert set(document["mcp_tools"]) == {
        "get_evidence",
        "get_evidence_content",
        "query_course",
        "search_materials",
    }
    assert document["mcp_tools"]["get_evidence_content"]["input_schema"][
        "required"
    ] == ["evidence_id"]
    for model in (MaterialSearchResult, EvidenceContentResult, CourseQuestionContext):
        schema = model.model_json_schema()
        assert schema["properties"]["schema_version"]["const"] == "1.0"


def test_new_version_field_is_backward_compatible_with_legacy_search_payload() -> None:
    legacy = {
        "query": "calculus",
        "course_ids": [],
        "indexed_document_count": 0,
        "indexed_chunk_count": 0,
        "skipped_document_count": 0,
        "hits": [],
    }
    result = MaterialSearchResult.model_validate(legacy)
    assert result.schema_version == "1.0"
    assert json.loads(result.model_dump_json())["schema_version"] == "1.0"
