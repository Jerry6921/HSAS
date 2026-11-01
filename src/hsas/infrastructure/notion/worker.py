"""Generate a macOS login worker definition without embedding credentials."""

from contextlib import contextmanager
import fcntl
from pathlib import Path
import plistlib
import sys

from hsas.infrastructure.storage.json_store import atomic_write


@contextmanager
def worker_lock(resources: Path):
    """Keep a single source controller alive for the entire worker process."""
    directory = resources / "notion"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "worker.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another Notion worker is already running") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def worker_plist(resources: Path, destination: Path, *, interval: int = 300) -> dict:
    if interval < 60:
        raise ValueError("Worker interval must be at least 60 seconds")
    source_root = Path(__file__).resolve().parents[3]
    logs = resources / "notion"
    logs.mkdir(parents=True, exist_ok=True)
    arguments = [sys.executable, "-m", "hsas", "--resources", str(resources), "notion", "work", "--interval", str(interval)]
    value = {"Label": "io.github.hiqs.notion-sync", "ProgramArguments": arguments,
        "EnvironmentVariables": {"PYTHONPATH": str(source_root)},
        "KeepAlive": True, "RunAtLoad": True,
        "StandardOutPath": str(logs / "worker.log"),
        "StandardErrorPath": str(logs / "worker-errors.log")}
    atomic_write(destination, plistlib.dumps(value))
    return {"plist": str(destination.resolve()), "interval_seconds": interval,
            "installed": False}
