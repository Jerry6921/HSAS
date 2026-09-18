"""Run the local HIQS MCP adapter over stdio."""

from __future__ import annotations

from hsas.core import build_port

from .build_server import build_mcp_server


def main() -> None:
    """Create the default CORE implementation and serve it over stdio."""
    build_mcp_server(build_port()).run()


if __name__ == "__main__":
    main()
