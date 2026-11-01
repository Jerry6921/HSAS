"""Generic atomic JSON/text/binary persistence for all HSAS applications."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from pydantic import BaseModel


def safe_filename(value: str) -> str:
    """Return a conservative filename component for local course artifacts."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return cleaned[:100] or "course"


def fsync_directory(directory: Path) -> None:
    """Flush directory metadata so a completed rename survives a power loss.

    ``os.replace`` publishes atomically, but the rename itself is only durable
    once the parent directory entry is flushed. Some filesystems reject fsync on
    a directory descriptor; there the rename has already happened, so this stays
    best-effort instead of failing an otherwise successful write.
    """
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def atomic_write(path: Path, value: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    binary = isinstance(value, bytes)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        mode = "wb" if binary else "w"
        kwargs = {} if binary else {"encoding": "utf-8"}
        with os.fdopen(descriptor, mode, **kwargs) as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        fsync_directory(path.parent)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return path


def write_json(path: Path, value: Any) -> Path:
    return atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2))


def write_model(path: Path, model: BaseModel) -> Path:
    return write_json(path, model.model_dump(mode="json"))


def write_text(path: Path, value: str) -> Path:
    return atomic_write(path, value)


def write_bytes(path: Path, value: bytes) -> Path:
    return atomic_write(path, value)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")
