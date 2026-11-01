"""Which MCP tools each workflow actually needs.

The full server exposes every HIQS tool. That is right for an operator working by
hand and wrong for an agent: most of the surface is irrelevant to the task at
hand, and a handful of tools must never run unattended because they open a
browser, request native permissions, halt work, or write outside the local store.

``HIQS_MCP_PROFILE`` selects a subset at startup. ``full`` (the default) keeps
every tool exposed, so existing configurations keep working. The profiles below
are declared as data and verified against the live server by
``scripts/generate_tool_profiles.py``; a new tool that is placed in no profile
fails that check, so the classification cannot drift silently.
"""

from __future__ import annotations

DEFAULT_PROFILE = "full"

#: Tools no Skill profile exposes. They need a human present, or they halt or
#: export work. Reachable by selecting the ``full`` profile explicitly.
OPERATOR_ONLY: frozenset[str] = frozenset(
    {
        "cancel_course_sync",
        "configure_apple_sync",
        "configure_apple_sync_worker",
        "export_notion",
        "login_class_planner",
        "login_moodle",
        "login_sis_course_info",
    }
)

#: Per-Skill tool sets. Each Skill documents the profile that serves it.
PROFILES: dict[str, frozenset[str]] = {
    "course-information": frozenset(
        {
            "apply_information_update",
            "acknowledge_pending_changes",
            "add_personal_inbox_entry",
            "apply_personal_inbox_entry",
            "check_apple_sync",
            "explain_evidence",
            "get_apple_sync_projection",
            "get_apple_sync_status",
            "get_attention",
            "get_calendar",
            "get_evidence",
            "get_evidence_content",
            "get_information",
            "get_information_update_schema",
            "get_pending_changes",
            "get_personal_inbox_entry",
            "get_status",
            "get_sync_status",
            "hydrate_course_materials",
            "list_materials",
            "list_personal_inbox",
            "query_course",
            "retry_failed_course_sync",
            "run_ocr",
            "save_recent_update_summary",
            "search_materials",
            "start_course_sync",
            "sync_apple",
            "sync_class_planner",
            "sync_sis_course_info",
            "sync_student_center",
            "validate_information_update",
            "verify_moodle_session",
        }
    ),
    "course-notes": frozenset(
        {
            "create_course_notes",
            "get_course_notes",
            "get_course_notes_schema",
            "get_evidence_content",
            "get_information",
            "get_status",
            "list_materials",
            "query_course",
            "read_course_note_source",
            "save_course_notes",
            "search_materials",
            "sync_notion",
        }
    ),
    "course-planning": frozenset(
        {
            "authorize_course_plan",
            "cancel_course_plan",
            "create_course_plan",
            "get_course_plan",
            "get_course_planning_schema",
            "get_information",
            "get_pending_changes",
            "next_course_plan_action",
            "reconcile_course_plan",
            "sync_sis_course_info",
            "sync_student_center",
        }
    ),
    "notion-workspace": frozenset(
        {
            "check_notion_connection",
            "get_information",
            "get_notion_controls",
            "get_notion_projection",
            "get_notion_status",
            "get_status",
            "sync_notion",
        }
    ),
}


def resolve_profile(name: str | None) -> frozenset[str] | None:
    """Return the exposed tool names, or ``None`` to expose the full server.

    ``None`` and empty input select the default. An unknown name is an error
    rather than a silent fall back to ``full``: a typo would otherwise hand an
    agent every operator tool while looking like it was restricted.
    """
    resolved = (name or "").strip() or DEFAULT_PROFILE
    if resolved == DEFAULT_PROFILE:
        return None
    try:
        return PROFILES[resolved]
    except KeyError:
        known = ", ".join([DEFAULT_PROFILE, *sorted(PROFILES)])
        raise ValueError(
            f"unknown HIQS_MCP_PROFILE {resolved!r}; choose one of: {known}"
        ) from None


__all__ = ["DEFAULT_PROFILE", "OPERATOR_ONLY", "PROFILES", "resolve_profile"]
