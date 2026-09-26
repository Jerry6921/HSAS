"""Generate committed JSON Schema snapshots for the public Agent evidence API."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from hsas.application.course_context import CourseQuestionContext
from hsas.application.material_search import EvidenceContentResult, MaterialSearchResult
from hsas.core import HIQSPort
from hsas.mcp import build_mcp_server


SCHEMA_VERSION = "1.0"
MODELS = (
    MaterialSearchResult,
    EvidenceContentResult,
    CourseQuestionContext,
)
AGENT_TOOLS = {
    "get_evidence",
    "get_evidence_content",
    "query_course",
    "search_materials",
}


def _mcp_tool_contracts() -> dict[str, Any]:
    server = build_mcp_server(Mock(spec=HIQSPort))
    tools = asyncio.run(server.list_tools())
    return {
        tool.name: {
            "input_schema": tool.input_schema,
            "output_schema": tool.output_schema,
        }
        for tool in tools
        if tool.name in AGENT_TOOLS
    }


def contract_document() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "contracts": {
            model.__name__: model.model_json_schema()
            for model in MODELS
        },
        "mcp_tools": _mcp_tool_contracts(),
    }


def render_contract_document() -> str:
    return json.dumps(contract_document(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> None:
    target = Path(__file__).parents[1] / "contracts" / "agent-evidence.schema.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_contract_document(), encoding="utf-8")
    print(f"Agent evidence contracts -> {target}")


if __name__ == "__main__":
    main()
