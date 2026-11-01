"""The EventKit helper integrity stamp must cover the compiled executable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hsas.infrastructure.apple import client as client_module
from hsas.infrastructure.apple.client import BRIDGE_STAMP_SCHEMA, NativeAppleGateway


class _Completed:
    returncode = 0
    stderr = ""


def _install_fake_toolchain(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):  # noqa: ANN001 - subprocess shim
        calls.append(list(command))
        if command[0] == "/usr/bin/xcrun":
            Path(command[-1]).write_bytes(b"compiled-eventkit-helper")
        return _Completed()

    monkeypatch.setattr(client_module.sys, "platform", "darwin")
    monkeypatch.setattr(client_module.subprocess, "run", fake_run)
    return calls


def _gateway(tmp_path: Path) -> NativeAppleGateway:
    return NativeAppleGateway(tmp_path)


def _stamp(gateway: NativeAppleGateway) -> dict:
    return json.loads((gateway.root / "bridge.sha256").read_text(encoding="utf-8"))


def _compiles(calls: list[list[str]]) -> int:
    return sum(1 for command in calls if command[0] == "/usr/bin/xcrun")


@pytest.fixture
def calls(tmp_path, monkeypatch):
    calls = _install_fake_toolchain(monkeypatch)
    return _gateway(tmp_path), calls


def test_stamp_records_source_target_and_binary(calls) -> None:
    gateway, compile_calls = calls

    bundle = gateway.build()

    stamp = _stamp(gateway)
    assert stamp["schema_version"] == BRIDGE_STAMP_SCHEMA
    assert stamp["binary_sha256"] == client_module._file_digest(
        bundle / "Contents/MacOS/HIQSAppleSync"
    )
    assert stamp["target"].endswith("apple-macosx14.0")


def test_reuses_helper_without_recompiling(calls) -> None:
    gateway, compile_calls = calls
    gateway.build()

    gateway.build()

    assert _compiles(compile_calls) == 1


def test_rebuilds_when_executable_is_replaced(calls) -> None:
    gateway, compile_calls = calls
    bundle = gateway.build()
    executable = bundle / "Contents/MacOS/HIQSAppleSync"
    executable.write_bytes(b"tampered-helper-binary")

    gateway.build()

    assert _compiles(compile_calls) == 2
    assert _stamp(gateway)["binary_sha256"] == client_module._digest(b"compiled-eventkit-helper")


def test_rebuilds_when_stamp_is_tampered(calls) -> None:
    gateway, compile_calls = calls
    gateway.build()
    stamp_path = gateway.root / "bridge.sha256"
    stamp = _stamp(gateway)
    stamp["source_sha256"] = "0" * 64
    stamp_path.write_text(json.dumps(stamp), encoding="utf-8")

    gateway.build()

    assert _compiles(compile_calls) == 2


def test_legacy_plain_stamp_forces_rebuild(calls) -> None:
    gateway, compile_calls = calls
    gateway.root.mkdir(parents=True, exist_ok=True)
    (gateway.root / "bridge.sha256").write_text("a" * 64, encoding="utf-8")

    gateway.build()

    assert _compiles(compile_calls) == 1


def test_stamp_is_private(calls) -> None:
    gateway, _compile_calls = calls

    gateway.build()

    mode = (gateway.root / "bridge.sha256").stat().st_mode & 0o777
    assert mode == 0o600


def test_codesign_is_verified_after_signing(calls) -> None:
    gateway, compile_calls = calls

    gateway.build()

    verify_calls = [
        command
        for command in compile_calls
        if command[:3] == ["/usr/bin/codesign", "--verify", "--strict"]
    ]
    assert len(verify_calls) == 1
