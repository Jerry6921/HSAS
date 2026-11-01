"""Native Apple Calendar/Reminders boundary."""

from typing import Any, Protocol


class AppleCalendarGateway(Protocol):
    def execute(self, payload: dict[str, Any]) -> dict[str, Any]: ...
