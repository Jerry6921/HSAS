"""Build and launch a named EventKit helper with private file-based IPC."""

from hashlib import sha256
from pathlib import Path
import plistlib
import platform
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any

from hsas.infrastructure.storage.json_store import read_json, write_json


class NativeAppleGateway:
    def __init__(self, resources: Path):
        self.root = resources / "apple"

    def build(self) -> Path:
        if sys.platform != "darwin":
            raise ValueError("Apple synchronization requires macOS 14 or later")
        source = Path(__file__).with_name("EventKitBridge.swift")
        bundle = self.root / "HIQS Apple Sync.app"
        contents = bundle / "Contents"
        executable = contents / "MacOS" / "HIQSAppleSync"
        target = f"{platform.machine()}-apple-macosx14.0"
        fingerprint = sha256(source.read_bytes() + target.encode()).hexdigest()
        stamp = self.root / "bridge.sha256"
        if executable.is_file() and stamp.is_file() and stamp.read_text() == fingerprint:
            return bundle
        executable.parent.mkdir(parents=True, exist_ok=True)
        info = {"CFBundleIdentifier": "io.github.hiqs.apple-sync", "CFBundleName": "HIQS Apple Sync",
                "CFBundleDisplayName": "HIQS Apple Sync", "CFBundleExecutable": "HIQSAppleSync",
                "CFBundlePackageType": "APPL", "CFBundleVersion": "1", "LSUIElement": True,
                "LSMinimumSystemVersion": "14.0",
                "NSCalendarsFullAccessUsageDescription": "HIQS 将已核实的课程日程同步到专用 HIQS 日历，并读回核对。",
                "NSRemindersFullAccessUsageDescription": "HIQS 将课程任务同步到专用提醒事项列表，保留你的完成状态和个人备注。"}
        (contents / "Info.plist").write_bytes(plistlib.dumps(info))
        result = subprocess.run(["/usr/bin/xcrun", "swiftc", "-swift-version", "5", "-framework", "AppKit",
                                 "-target", target,
                                 "-module-cache-path", str(self.root / "swift-cache"),
                                 "-framework", "EventKit", str(source), "-o", str(executable)],
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise ValueError("EventKit helper compilation failed: " + result.stderr[-3000:])
        subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(bundle)],
                       check=True, capture_output=True, timeout=30)
        stamp.write_text(fingerprint)
        return bundle

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        bundle = self.build()
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)
        with TemporaryDirectory(dir=self.root, prefix="request-") as temporary:
            request, response = Path(temporary) / "request.json", Path(temporary) / "response.json"
            write_json(request, payload)
            request.chmod(0o600)
            try:
                process = subprocess.run(["/usr/bin/open", "-W", "-n", "-a", str(bundle), "--args",
                                          str(request), str(response)], capture_output=True,
                                         timeout=150 if payload.get("operation") == "authorize" else 90)
            except subprocess.TimeoutExpired as exc:
                raise ValueError("Apple helper timed out; reconcile its state before retrying") from exc
            if not response.is_file():
                reason = process.stderr.decode("utf-8", errors="replace")[-1200:]
                raise ValueError(f"Apple helper produced no receipt (launcher exit {process.returncode}): {reason}")
            result = read_json(response)
            if not isinstance(result, dict):
                raise ValueError("Apple helper returned an invalid receipt")
            return result
