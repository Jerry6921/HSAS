"""External workspace boundary used by the Notion delivery service."""

from typing import Any, Protocol


class NotionWorkspaceGateway(Protocol):
    def synchronize(self, projection: dict[str, Any]) -> dict[str, Any]: ...

    def check_connection(self) -> dict[str, Any]: ...
