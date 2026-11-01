"""LaunchAgent installation for deterministic Apple delivery, without an Agent."""

from hashlib import sha256
import os
from pathlib import Path
import plistlib
import subprocess
import sys

from hsas.infrastructure.storage.json_store import atomic_write


def worker_definition(resources: Path, interval: int = 300) -> dict:
    if interval < 60 or interval > 86400:
        raise ValueError("Apple synchronization interval must be 60–86400 seconds")
    label = "io.github.hiqs.apple-sync." + sha256(str(resources.resolve()).encode()).hexdigest()[:12]
    directory = resources / "apple"
    return {"Label": label,
            "ProgramArguments": [sys.executable, "-m", "hsas", "--resources", str(resources.resolve()), "apple", "sync"],
            "EnvironmentVariables": {"PYTHONPATH": str(Path(__file__).resolve().parents[3])},
            "StartInterval": interval, "RunAtLoad": True, "ThrottleInterval": 30,
            "WatchPaths": [str((resources / "information.json").resolve())],
            "StandardOutPath": str(directory / "worker.log"),
            "StandardErrorPath": str(directory / "worker-errors.log")}


def worker_status(resources: Path) -> dict:
    definition = worker_definition(resources)
    path = Path.home() / "Library/LaunchAgents" / (definition["Label"] + ".plist")
    loaded = False
    if sys.platform == "darwin":
        loaded = subprocess.run(["/bin/launchctl", "print", f"gui/{os.getuid()}/{definition['Label']}"],
                                capture_output=True, timeout=10).returncode == 0
    return {"loaded": loaded, "plist": str(path), "label": definition["Label"]}


def set_worker(resources: Path, *, enabled: bool, interval: int = 300) -> dict:
    if sys.platform != "darwin":
        raise ValueError("Apple login synchronization requires macOS")
    definition = worker_definition(resources, interval)
    path = Path.home() / "Library/LaunchAgents" / (definition["Label"] + ".plist")
    domain = f"gui/{os.getuid()}"
    status = worker_status(resources)
    if status["loaded"]:
        subprocess.run(["/bin/launchctl", "bootout", f"{domain}/{definition['Label']}"],
                       check=True, capture_output=True, timeout=15)
    if enabled:
        (resources / "apple").mkdir(parents=True, exist_ok=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, plistlib.dumps(definition))
        path.chmod(0o600)
        subprocess.run(["/bin/launchctl", "bootstrap", domain, str(path)],
                       check=True, capture_output=True, timeout=15)
    else:
        path.unlink(missing_ok=True)
    result = worker_status(resources)
    if result["loaded"] != enabled:
        raise ValueError("Apple login worker registration could not be verified")
    return {**result, "enabled": enabled, "interval_seconds": interval if enabled else None}
