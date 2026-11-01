"""Generate the notes checkpoint schema and MCP input contracts."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import Mock

from hsas.application.course_notes import NotesCheckpoint
from hsas.core import HIQSPort
from hsas.mcp import build_mcp_server


def render_notes_contracts() -> str:
    server = build_mcp_server(Mock(spec=HIQSPort))
    tools = asyncio.run(server.list_tools())
    return json.dumps({
        "schema_version": "1.0",
        "checkpoint": NotesCheckpoint.model_json_schema(),
        "mcp_tools": {
            tool.name: tool.input_schema for tool in tools
            if tool.name in {"create_course_notes", "get_course_notes", "get_course_notes_schema",
                             "read_course_note_source", "save_course_notes"}
        },
    }, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "contracts/course-notes.schema.json"
    target.write_text(render_notes_contracts(), encoding="utf-8")
    print(target)
