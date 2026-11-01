"""Generate the committed MCP tool-profile contract.

The contract records which tools exist, which workflow profile exposes them, and
which tools are human-only. ``scripts/check_all.py`` compares it in memory, so
adding a tool without giving it a profile fails the gate instead of silently
widening the surface an agent sees.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import Mock

from hsas.core import HIQSPort
from hsas.mcp import build_mcp_server
from hsas.mcp.profiles import DEFAULT_PROFILE, HUMAN_ONLY, PROFILES


def render_tool_profiles() -> str:
    server = build_mcp_server(Mock(spec=HIQSPort))
    tools = sorted(tool.name for tool in asyncio.run(server.list_tools()))
    return (
        json.dumps(
            {
                "schema_version": "1.0",
                "default_profile": DEFAULT_PROFILE,
                "tool_count": len(tools),
                "tools": tools,
                "profiles": {
                    name: sorted(members) for name, members in sorted(PROFILES.items())
                },
                "human_only": sorted(HUMAN_ONLY),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def main() -> None:
    target = Path(__file__).resolve().parents[1] / "contracts" / "mcp-tool-profiles.json"
    target.write_text(render_tool_profiles(), encoding="utf-8")
    print(f"MCP tool profiles -> {target}")


if __name__ == "__main__":
    main()
