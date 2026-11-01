import asyncio
from unittest.mock import Mock

from hsas.core import HIQSPort
from hsas.mcp import build_mcp_server


def test_mcp_server_exposes_port_use_cases() -> None:
    port = Mock(spec=HIQSPort)
    server = build_mcp_server(port)

    tools = asyncio.run(server.list_tools())

    assert {tool.name for tool in tools} == {
        "get_apple_sync_status", "get_apple_sync_projection", "configure_apple_sync",
        "check_apple_sync", "sync_apple", "configure_apple_sync_worker",
        "acknowledge_pending_changes",
        "add_course",
        "add_personal_inbox_entry",
        "apply_information_update",
        "save_recent_update_summary",
        "apply_personal_inbox_entry",
        "cancel_course_sync",
        "delete_courses",
        "get_calendar",
        "get_notion_projection",
        "get_notion_controls",
        "get_notion_status",
        "check_notion_connection",
        "sync_notion",
        "export_notion",
        "get_attention",
        "get_information",
        "get_information_update_schema",
            "get_evidence",
            "explain_evidence",
        "get_evidence_content",
        "get_pending_changes",
        "get_personal_inbox_entry",
        "get_status",
            "get_sync_status",
            "hydrate_course_materials",
        "list_materials",
        "create_course_plan",
        "get_course_plan",
        "get_course_planning_schema",
        "authorize_course_plan",
        "reconcile_course_plan",
        "next_course_plan_action",
        "cancel_course_plan",
        "create_course_notes",
        "get_course_notes",
        "get_course_notes_schema",
        "read_course_note_source",
        "save_course_notes",
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
