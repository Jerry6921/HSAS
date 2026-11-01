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
    def get_apple_sync_status() -> dict[str, Any]:
        """Return Apple Calendar/Reminders configuration, receipt and login worker status."""
        return port.apple_status()

    @server.tool()
    def get_apple_sync_projection() -> dict[str, Any]:
        """Preview source-backed events and actionable reminders without changing Apple data."""
        return port.apple_projection()

    @server.tool()
    def configure_apple_sync(account_mode: str = "icloud", confirmed: bool = False) -> dict[str, Any]:
        """Choose the authorized Apple account and request native macOS permissions."""
        return port.apple_configure({"account_mode": account_mode, "confirmed": confirmed})

    @server.tool()
    def check_apple_sync() -> dict[str, Any]:
        """Read native permission/account inventory; never substitute a different account."""
        return port.apple_check()

    @server.tool()
    def sync_apple() -> dict[str, Any]:
        """Sync authorized HIQS facts to dedicated Apple containers and verify readback.

        Requires user authorization for Apple/iCloud delivery. Preserves personal
        completion/alarms/notes; this never writes canonical facts or Notion status.
        """
        return port.apple_sync()

    @server.tool()
    def configure_apple_sync_worker(enabled: bool = True, interval_seconds: int = 300,
                                    confirmed: bool = False) -> dict[str, Any]:
        """Enable/disable automatic Apple delivery after verified setup; retain Apple data."""
        return port.apple_worker({"enabled": enabled, "interval_seconds": interval_seconds, "confirmed": confirmed})

    @server.tool()
    def get_notion_controls() -> dict[str, Any]:
        """Return real source-sync progress and the existing AI review prompt."""
        return port.notion_controls()

    @server.tool()
    def get_notion_projection() -> dict[str, Any]:
        """Return stable-ID courses, tasks, calendar occurrences and original files.

        This reads validated information.json. Notion personal status, notes and
        user-created page content must never be replaced during an upsert.
        """
        return port.notion_projection()

    @server.tool()
    def get_notion_status() -> dict[str, Any]:
        """Return local connection and last-sync results without credentials."""
        return port.notion_status()

    @server.tool()
    def check_notion_connection() -> dict[str, Any]:
        """Verify the independently configured connection and database access."""
        return port.notion_check()

    @server.tool()
    def sync_notion() -> dict[str, Any]:
        """Upsert course facts and upload original materials to configured Notion.

        External write: use only when the user has authorized HIQS-to-Notion sync.
        Stable IDs prevent duplicates; personal status and notes are preserved.
        Partial failures are resumable. This never applies canonical facts.
        """
        return port.notion_sync()

    @server.tool()
    def export_notion(
        destination: str | None = None,
        include_files: bool = True,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """Export CSV/Markdown/ICS and an optional ZIP of original materials.

        The package contains private course content. Omitting ``destination``
        writes under the private resources ``exports/`` directory; Agent calls
        cannot write outside that directory. Requires ``confirmed=True``.
        """
        return port.notion_export(
            {
                "destination": destination,
                "include_files": include_files,
                "confirmed": confirmed,
            }
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
        """Validate the merged candidate without writing; inspect quality_audit.

        Audit findings identify unknown action dates, weak provenance, duplicate
        candidates and inconsistent dates. Schema validity is not source-reading
        completeness or semantic accuracy.
        """
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
    def save_recent_update_summary(
        applied_at: str,
        headline: str,
        body: str,
        highlights: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Save a concise Agent summary for the exact latest applied report.

        Select at most six highlights by category, course_id and record_id from
        the recent_update returned by apply_information_update.
        """
        return port.save_recent_update_summary({
            "applied_at": applied_at,
            "headline": headline,
            "body": body,
            "highlights": highlights or [],
        })

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
    def get_course_planning_schema() -> dict[str, Any]:
        """Return request, official observation and scoped authorization JSON schemas."""
        return port.course_planning_schema()

    @server.tool()
    def create_course_plan(request: dict[str, Any], confirmed: bool = False) -> dict[str, Any]:
        """Persist a reviewed candidate pool, goals and constraints. No SIS submission.

        Use hiqs-course-planning for syllabus/SIS evidence and browser execution.
        All required lecture/tutorial/lab components belong to one option.
        """
        return port.create_course_plan({"request": request, "confirmed": confirmed})

    @server.tool()
    def get_course_plan(run_id: str | None = None, observation_sha256: str | None = None) -> dict[str, Any]:
        """List runs or read exact plans, attempts, locks and actual official readback.

        Pass a plan/attempt observation_sha256 to read its immutable input snapshot.
        Check executor/background_running; stored waiting is not a running worker.
        """
        return port.course_plan(run_id, observation_sha256)

    @server.tool()
    def authorize_course_plan(run_id: str, expected_revision: int, request_sha256: str,
                             authorization: dict[str, Any], confirmed: bool = False) -> dict[str, Any]:
        """Bind human authorization to an exact account, term, candidate pool and limits.

        Development instructions alone never authorize a real SIS enrolment.
        """
        return port.authorize_course_plan({"run_id": run_id, "expected_revision": expected_revision,
            "request_sha256": request_sha256, "authorization": authorization, "confirmed": confirmed})

    @server.tool()
    def reconcile_course_plan(run_id: str, expected_revision: int,
                              observation: dict[str, Any], confirmed: bool = False) -> dict[str, Any]:
        """Save complete official account/component readback and replan remaining goals.

        Agent supplies observed source, locator, hash, capture time and raw school
        status. Clicks/HTTP success are insufficient. Include explicit absent +
        classified attempt outcome to resolve an unknown submission as failed.
        This tool validates evidence structure; it does not independently fetch SIS.
        """
        return port.reconcile_course_plan({"run_id": run_id, "expected_revision": expected_revision,
            "observation": observation, "confirmed": confirmed})

    @server.tool()
    def next_course_plan_action(run_id: str, expected_revision: int,
                                confirmed: bool = False) -> dict[str, Any]:
        """Reserve at most one foreground Agent submission in the authorized scope.

        submit is a one-use browser instruction, not an SIS request. Recheck the
        official preflight immediately and respect valid_until. On interruption,
        fetch/reconcile the unknown attempt instead of replaying it. No drop/swap.
        """
        return port.next_course_plan_action({"run_id": run_id, "expected_revision": expected_revision,
                                            "confirmed": confirmed})

    @server.tool()
    def cancel_course_plan(run_id: str, expected_revision: int,
                           confirmed: bool = False) -> dict[str, Any]:
        """Stop future actions; preserve enrolled courses and unresolved submissions."""
        return port.cancel_course_plan({"run_id": run_id, "expected_revision": expected_revision,
                                       "confirmed": confirmed})

    @server.tool()
    def create_course_notes(
        course_id: str, scope: str, language: str = "English", confirmed: bool = False,
    ) -> dict[str, Any]:
        """Start a local notes run from an exact archived course ID.

        Snapshots the material inventory and hashes, without changing course facts
        or starting background generation. Use hiqs-course-notes to author the
        entire set in internal batches. Reuse get_course_notes runs on retry.
        """
        return port.create_course_notes({
            "course_id": course_id, "scope": scope, "language": language, "confirmed": confirmed,
        })

    @server.tool()
    def get_course_notes_schema() -> dict[str, Any]:
        """Return the exact checkpoint schema for save_course_notes.update."""
        return port.course_notes_schema()

    @server.tool()
    def get_course_notes(run_id: str | None = None, artifact_id: str | None = None) -> dict[str, Any]:
        """List resumable runs or read one checkpoint/artifact and verify local delivery."""
        return port.course_notes(run_id, artifact_id)

    @server.tool()
    def read_course_note_source(
        run_id: str, source_id: str, offset: int = 0, limit: int = 12000,
    ) -> dict[str, Any]:
        """Read bounded source text with next_offset/eof; continue until eof.

        Source IDs belong to one run. Original paths and extraction warnings
        remain in its inventory for visual review. Text delivery does not prove
        reading or visual completeness; record the Agent review in a checkpoint.
        """
        return port.read_course_note_source({
            "run_id": run_id, "source_id": source_id, "offset": offset, "limit": limit,
        })

    @server.tool()
    def save_course_notes(
        run_id: str, expected_revision: int, update: dict[str, Any], confirmed: bool = False,
    ) -> dict[str, Any]:
        """Atomically checkpoint notes and read back Markdown exports.

        Call get_course_notes_schema for the exact update schema.
        Updates upsert source_reviews/artifacts; units/questions replace their
        respective plans when supplied. Complete requires all planned units,
        source reviews, overview, question-map, review and coverage artifacts.
        Partial/blocked needs status_note. Stale revisions fail without writes.
        External publication receipts are Agent-reported, separate from content.
        """
        return port.save_course_notes({
            "run_id": run_id, "expected_revision": expected_revision,
            "update": update, "confirmed": confirmed,
        })

    @server.tool()
    def list_materials(course_ids: list[str] | None = None) -> dict[str, Any]:
        """Inventory files, all activities and explicit collection/reading gaps.

        Inspect coverage.gaps, OCR and unit counts before claiming full review.
        inventory_ready is not a declaration that the Agent read the sources.
        """
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
    def explain_evidence(evidence_id: str) -> dict[str, Any]:
        """Explain what evidence supports, how it was obtained, and known limits."""
        return port.explain_evidence(evidence_id)

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
    def start_course_sync(
        course: str | None = None,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """Start a background unified sync for all courses or one course.

        ``course`` accepts an HKU course code such as ``BMED2206``; omit it to
        synchronize every current-semester course. Background collection opens a
        browser session and rewrites course snapshots, so the call requires
        ``confirmed=True``.
        """
        payload: dict[str, Any] = {"confirmed": confirmed}
        if course is not None:
            payload["course"] = course
        return port.start_course_sync(payload)

    @server.tool()
    def retry_failed_course_sync(confirmed: bool = False) -> dict[str, Any]:
        """Retry only the courses that failed during the latest sync."""
        return port.retry_failed_course_sync({"confirmed": confirmed})

    @server.tool()
    def cancel_course_sync(confirmed: bool = False) -> dict[str, Any]:
        """Request cancellation of the active background sync."""
        return port.cancel_course_sync({"confirmed": confirmed})

    @server.tool()
    def hydrate_course_materials(course_id: str) -> dict[str, Any]:
        """Download and index one deferred Moodle course when Agent needs its files.

        The normal sync records Moodle structure and source links first. Call this
        tool immediately before querying a course's local material evidence; it is
        safe to call again because the course snapshot publisher preserves hashes.
        """
        return port.hydrate_course_materials({"course_id": course_id})

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
    def sync_sis_course_info(confirmed: bool = False, course_codes: list[str] | None = None) -> dict[str, Any]:
        """Read official catalogue pages, including explicit unselected course_codes."""
        return port.synchronize_sis_course_info({"confirmed": confirmed, "course_codes": course_codes})

    # Course add/delete are compatibility-UI maintenance actions, not Agent
    # tools: canonical facts must be written through the validated apply flow
    # (coverage, audit digest, checkpoints and index refresh all live there).
    return server
