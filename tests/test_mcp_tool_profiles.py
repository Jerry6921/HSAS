"""The MCP tool surface must stay classified and profile-selectable."""

from __future__ import annotations

import asyncio
from unittest.mock import Mock

import pytest

from hsas.core import HIQSPort
from hsas.mcp import build_mcp_server
from hsas.mcp.profiles import DEFAULT_PROFILE, OPERATOR_ONLY, PROFILES, resolve_profile


def _tool_names(**kwargs) -> frozenset[str]:
    server = build_mcp_server(Mock(spec=HIQSPort), **kwargs)
    return frozenset(tool.name for tool in asyncio.run(server.list_tools()))


def test_every_tool_has_exactly_one_place_in_the_classification() -> None:
    all_tools = _tool_names()
    classified = set(OPERATOR_ONLY)
    for members in PROFILES.values():
        classified |= set(members)

    assert OPERATOR_ONLY.isdisjoint(set().union(*PROFILES.values()))
    assert classified == set(all_tools), (
        "tools with no profile and no operator listing: "
        f"{sorted(set(all_tools) - classified)}; "
        f"names in a profile that do not exist: {sorted(classified - set(all_tools))}"
    )


def test_operator_tools_are_not_reachable_from_any_skill_profile() -> None:
    for name in PROFILES:
        assert _tool_names(profile=name).isdisjoint(OPERATOR_ONLY), name


def test_a_profile_exposes_exactly_its_declared_tools() -> None:
    for name, members in PROFILES.items():
        assert _tool_names(profile=name) == members, name


def test_the_default_profile_exposes_the_full_surface() -> None:
    assert resolve_profile(None) is None
    assert resolve_profile("") is None
    assert resolve_profile(DEFAULT_PROFILE) is None
    assert _tool_names() == _tool_names(profile=DEFAULT_PROFILE)


def test_an_unknown_profile_fails_loudly_instead_of_exposing_everything() -> None:
    with pytest.raises(ValueError, match="unknown HIQS_MCP_PROFILE"):
        resolve_profile("cource-notes")
    with pytest.raises(ValueError, match="unknown HIQS_MCP_PROFILE"):
        build_mcp_server(Mock(spec=HIQSPort), profile="nope")


def test_profiles_are_narrow_enough_to_mean_something() -> None:
    full = len(_tool_names())
    for name, members in PROFILES.items():
        assert len(members) < full, f"{name} does not narrow the surface at all"
