import asyncio
from unittest.mock import Mock

from hsas.core import HIQSPort
from hsas.mcp import build_mcp_server


def test_mcp_server_exposes_port_use_cases() -> None:
    port = Mock(spec=HIQSPort)
    server = build_mcp_server(port)

    tools = asyncio.run(server.list_tools())

    assert {tool.name for tool in tools} == {
        "apply_personal_inbox_entry",
        "cancel_course_sync",
        "get_calendar",
        "get_information",
        "get_sync_status",
        "retry_failed_course_sync",
        "run_ocr",
        "start_course_sync",
    }
