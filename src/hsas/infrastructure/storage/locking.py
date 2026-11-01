"""Cross-process advisory locks for shared JSON state.

``atomic_write`` publishes by ``os.replace``, which swaps the inode. Locking the
data file itself would therefore protect a stale inode, so every writer locks a
dedicated, stable lock file instead.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
from pathlib import Path

CANONICAL_INFORMATION_LOCK = Path(".transactions") / "information.lock"


@contextmanager
def exclusive_file_lock(path: Path) -> Iterator[None]:
    """Hold an exclusive advisory lock on ``path`` until the block exits."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def canonical_information_lock(resources_dir: Path):
    """Serialize canonical ``information.json`` read-modify-write cycles.

    The MCP server is long-lived while the CLI and the Apple login worker run in
    separate processes, so the process-local ``threading.Lock`` is not enough:
    without this lock two writers can each load the store, merge their own
    change and save, silently dropping the other writer's records.
    """
    return exclusive_file_lock(resources_dir / CANONICAL_INFORMATION_LOCK)


__all__ = ["CANONICAL_INFORMATION_LOCK", "canonical_information_lock", "exclusive_file_lock"]
