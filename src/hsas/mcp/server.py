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
    def get_status() -> dict[str, Any]:
        """Return source, review, OCR, Inbox and active-sync status in one packet."""
        return port.status_snapshot()

    @server.tool()
    def get_attention(horizon_days: int = 14) -> dict[str, Any]:
        """Return ranked attention signals with evidence and allowed actions."""
        return port.attention_snapshot(horizon_days)

    @server.tool()
    def get_information_update_schema() -> dict[str, Any]:
        """Return the exact JSON schema accepted for validated information writes."""
        return port.information_update_schema()

    @server.tool()
    def validate_information_update(update: dict[str, Any]) -> dict[str, Any]:
        """Validate a complete course-information update without changing data."""
        return port.validate_information_update({"update": update})

    @server.tool()
    def apply_information_update(
        update: dict[str, Any],
        review_batches: dict[str, Any] | None = None,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """Apply reviewed facts and then checkpoint supplied source batches."""
        return port.apply_information_update(
            {
                "update": update,
                "review_batches": review_batches or {},
                "confirmed": confirmed,
            }
        )

    @server.tool()
    def get_calendar() -> str:
        """Return the deterministic RFC 5545 calendar projection."""
        return port.calendar_ics().decode("utf-8")

    @server.tool()
    def query_course(
        question: str,
        course_ids: list[str] | None = None,
        material_limit: int = 6,
        item_limit: int = 20,
    ) -> dict[str, Any]:
        """Return a cited RAG packet from structured facts and local source text."""
        return port.query_course(
            {
                "question": question,
                "course_ids": course_ids,
                "material_limit": material_limit,
                "item_limit": item_limit,
            }
        )

    @server.tool()
    def list_materials(course_ids: list[str] | None = None) -> dict[str, Any]:
        """List downloaded files, hashes and extracted-text sidecars."""
        return port.materials_manifest(course_ids)

    @server.tool()
    def search_materials(
        query: str,
        course_ids: list[str] | None = None,
        limit: int = 6,
    ) -> dict[str, Any]:
        """Search extracted materials and return page-aware evidence chunks."""
        return port.search_materials(
            {"query": query, "course_ids": course_ids, "limit": limit}
        )

    @server.tool()
    def get_evidence(evidence_id: str) -> dict[str, Any]:
        """Resolve one evidence node and its provenance neighborhood."""
        return port.get_evidence(evidence_id)

    @server.tool()
    def get_evidence_content(
        evidence_id: str,
        chunk_index: int | None = None,
        context_chunks: int = 1,
    ) -> dict[str, Any]:
        """Hydrate one selected evidence chunk and a small adjacent neighborhood."""
        return port.get_evidence_content(
            {
                "evidence_id": evidence_id,
                "chunk_index": chunk_index,
                "context_chunks": context_chunks,
            }
        )

    @server.tool()
    def get_pending_changes(
        source: str = "moodle",
        course_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Export an exact pending batch for Moodle, SIS, enrolment or Class Planner."""
        return port.pending_changes({"source": source, "course_ids": course_ids})

    @server.tool()
    def acknowledge_pending_changes(
        source: str,
        batch: dict[str, Any],
        reviewed_no_information_change: bool = False,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """Checkpoint a still-current batch only after review found no fact change."""
        return port.acknowledge_changes(
            {
                "source": source,
                "batch": batch,
                "reviewed_no_information_change": reviewed_no_information_change,
                "confirmed": confirmed,
            }
        )

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
    def list_personal_inbox() -> dict[str, Any]:
        """Return pending personal drafts and their field-level previews."""
        return port.personal_inbox_snapshot()

    @server.tool()
    def get_personal_inbox_entry(entry_id: str) -> dict[str, Any]:
        """Return the complete validated update stored in one personal draft."""
        return port.personal_inbox_entry(entry_id)

    @server.tool()
    def add_personal_inbox_entry(
        title: str,
        update: dict[str, Any],
        note: str | None = None,
    ) -> dict[str, Any]:
        """Stage a user-provided update for preview without applying it."""
        return port.add_personal_inbox(
            {"title": title, "update": update, "note": note}
        )

    @server.tool()
    def apply_personal_inbox_entry(
        entry_id: str,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """Apply one staged personal-information draft after confirmation."""
        return port.apply_personal_inbox(
            {"entry_id": entry_id, "confirmed": confirmed}
        )

    @server.tool()
    def verify_moodle_session() -> dict[str, Any]:
        """Verify the live Moodle session rather than trusting stale state."""
        return port.verify_moodle_session()

    @server.tool()
    def login_moodle(confirmed: bool = False) -> dict[str, Any]:
        """Open a visible Moodle login flow for user-completed SSO and MFA."""
        return port.login_moodle({"confirmed": confirmed})

    @server.tool()
    def sync_student_center(confirmed: bool = False) -> dict[str, Any]:
        """Capture the current Student Center enrolment snapshot."""
        return port.synchronize_sis_enrollment({"confirmed": confirmed})

    @server.tool()
    def login_class_planner(confirmed: bool = False) -> dict[str, Any]:
        """Open the visible HKU Portal login flow for Class Planner."""
        return port.login_class_planner({"confirmed": confirmed})

    @server.tool()
    def sync_class_planner(confirmed: bool = False) -> dict[str, Any]:
        """Synchronize the official timetable snapshot."""
        return port.synchronize_class_planner({"confirmed": confirmed})

    @server.tool()
    def login_sis_course_info(confirmed: bool = False) -> dict[str, Any]:
        """Open the visible HKU SIS login flow."""
        return port.login_sis_course_info({"confirmed": confirmed})

    @server.tool()
    def sync_sis_course_info(confirmed: bool = False) -> dict[str, Any]:
        """Synchronize cleaned official HKU SIS course pages."""
        return port.synchronize_sis_course_info({"confirmed": confirmed})

    @server.tool()
    def add_course(course: dict[str, Any], confirmed: bool = False) -> dict[str, Any]:
        """Add one validated course record after explicit confirmation."""
        return port.add_course({"course": course, "confirmed": confirmed})

    @server.tool()
    def delete_courses(
        course_ids: list[str],
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """Delete selected courses and related local data after confirmation."""
        return port.delete_courses(
            {"course_ids": course_ids, "confirmed": confirmed}
        )

    return server
