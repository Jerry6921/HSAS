"""Read-only operational status projection for the CORE facade."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class OperationalStatusService:
    """Compose the stable status packet consumed by UI, MCP and agents."""

    def __init__(
        self,
        information_snapshot: Callable[[], dict[str, Any]],
        sync_status: Callable[[], dict[str, Any]],
    ) -> None:
        self._information_snapshot = information_snapshot
        self._sync_status = sync_status

    def snapshot(self) -> dict[str, Any]:
        snapshot = self._information_snapshot()
        return {
            "available": snapshot["available"],
            "updated_at": snapshot["updated_at"],
            "summary": snapshot["summary"],
            "pending_review": snapshot["pending_review"],
            "material_status": snapshot["material_status"],
            "review_closure": snapshot["review_closure"],
            "personal_inbox": snapshot["personal_inbox"],
            "moodle_session": snapshot["moodle_session"],
            "sis_enrollment": snapshot["sis_enrollment"],
            "class_planner": snapshot["class_planner"],
            "sis_course_info": snapshot["sis_course_info"],
            "sync": self._sync_status(),
        }
