import asyncio
from unittest.mock import Mock

from hsas.core import HIQSPort
from hsas.mcp import build_mcp_server


def test_mcp_server_exposes_port_use_cases() -> None:
    port = Mock(spec=HIQSPort)
    server = build_mcp_server(port)

    tools = asyncio.run(server.list_tools())

    assert {tool.name for tool in tools} == {
        "acknowledge_pending_changes",
        "add_course",
        "add_personal_inbox_entry",
        "apply_information_update",
        "apply_personal_inbox_entry",
        "cancel_course_sync",
        "delete_courses",
        "get_calendar",
        "get_information",
        "get_information_update_schema",
        "get_pending_changes",
        "get_personal_inbox_entry",
        "get_status",
        "get_sync_status",
        "list_materials",
        "list_personal_inbox",
        "login_class_planner",
        "login_moodle",
        "login_sis_course_info",
        "query_course",
        "retry_failed_course_sync",
        "run_ocr",
        "search_materials",
        "start_course_sync",
        "sync_class_planner",
        "sync_sis_course_info",
        "sync_student_center",
        "validate_information_update",
        "verify_moodle_session",
    }
