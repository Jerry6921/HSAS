"""Run the local HIQS MCP adapter over stdio."""

from __future__ import annotations

import argparse
import os

from hsas.core import build_port

from .profiles import DEFAULT_PROFILE, PROFILES
from .server import build_mcp_server


def main() -> None:
    """Create the default CORE implementation and serve it over stdio."""
    parser = argparse.ArgumentParser(
        prog="hiqs-mcp",
        description="Expose HIQS tools to an MCP client over stdio.",
    )
    parser.add_argument(
        "--profile",
        default=os.environ.get("HIQS_MCP_PROFILE"),
        metavar="NAME",
        help=(
            "Expose only one workflow's tools. "
            f"Available: {', '.join([DEFAULT_PROFILE, *sorted(PROFILES)])}. "
            "Defaults to HIQS_MCP_PROFILE, else the full surface."
        ),
    )
    args = parser.parse_args()
    try:
        server = build_mcp_server(build_port(), profile=args.profile)
    except ValueError as exc:
        parser.error(str(exc))
    server.run()


if __name__ == "__main__":
    main()
