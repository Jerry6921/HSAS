"""What an agent sees of a tool is its name and its description.

A tool without a description is unusable by choice, and a tool wired to a port
method that no longer exists fails only when somebody calls it. Both are cheap to
check statically, so they are checked here instead of being discovered later.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import Mock

from hsas.core import HIQSPort
from hsas.mcp import build_mcp_server

SERVER = Path(__file__).parents[1] / "src" / "hsas" / "mcp" / "server.py"


def _registered() -> list:
    server = build_mcp_server(Mock(spec=HIQSPort))
    return asyncio.run(server.list_tools())


def test_tool_names_are_unique() -> None:
    names = [tool.name for tool in _registered()]
    duplicates = {name for name in names if names.count(name) > 1}
    assert duplicates == set(), f"duplicated tool names are silently dropped: {duplicates}"


def test_every_tool_describes_itself() -> None:
    undocumented = [tool.name for tool in _registered() if not (tool.description or "").strip()]
    assert undocumented == [], f"tools an agent cannot understand: {undocumented}"


def test_every_tool_calls_a_method_that_HIQSPort_declares() -> None:
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    declared = {name for name in dir(HIQSPort) if not name.startswith("_")}
    missing: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for call in ast.walk(node):
            if (
                isinstance(call, ast.Attribute)
                and isinstance(call.value, ast.Name)
                and call.value.id == "port"
                and call.attr not in declared
            ):
                missing.setdefault(node.name, []).append(call.attr)
    assert missing == {}, f"tools wired to methods HIQSPort does not declare: {missing}"
