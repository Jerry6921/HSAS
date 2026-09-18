"""Build an MCP server whose tools depend only on the public HIQS port."""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer

from hsas.core import HIQSPort


def build_mcp_server(port: HIQSPort) -> MCPServer:
    """Bind typed MCP tools to an injected HIQS application port."""
    server = MCPServer(
        "HIQS",
        instructions=(
            "Use HIQS as the canonical local course-information service. "
            "Read evidence before drawing conclusions and never treat missing "
            "source coverage as a conflict. Write operations require explicit "
            "confirmation in their payload."
        ),
    )

    @server.tool()
    def get_information() -> dict[str, Any]:
        """Return validated courses, information items, provenance and review status."""
        return port.information_snapshot()

    @server.tool()
    def get_calendar() -> str:
        """Return the deterministic RFC 5545 calendar projection."""
        return port.calendar_ics().decode("utf-8")

    @server.tool()
    def get_sync_status() -> dict[str, Any]:
        """Return current or most recent unified course synchronization status."""
        return port.course_sync_status()

    @server.tool()
    def start_course_sync(course: str | None = None) -> dict[str, Any]:
        """Start a background unified sync for all courses or one Moodle course."""
        payload: dict[str, Any] = {}
        if course is not None:
            payload["course"] = course
        return port.start_course_sync(payload)

    @server.tool()
    def retry_failed_course_sync() -> dict[str, Any]:
        """Retry only the courses that failed during the latest sync."""
        return port.retry_failed_course_sync({})

    @server.tool()
    def cancel_course_sync() -> dict[str, Any]:
        """Request cancellation of the active background sync."""
        return port.cancel_course_sync({})

    @server.tool()
    def run_ocr(confirmed: bool = False) -> dict[str, Any]:
        """Process the local OCR queue after explicit confirmation."""
        return port.process_ocr_queue({"confirmed": confirmed})

    @server.tool()
    def apply_personal_inbox_entry(
        entry_id: str,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """Apply one staged personal-information draft after confirmation."""
        return port.apply_personal_inbox(
            {"entry_id": entry_id, "confirmed": confirmed}
        )

    return server
