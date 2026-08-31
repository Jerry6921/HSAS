from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def safe_filename(value: str) -> str:
    """Return a conservative filename component for local course artifacts."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return cleaned[:100] or "course"


def _atomic_write(path: Path, value: str | bytes) -> Path:
    """Write beside the destination and atomically replace it when complete."""
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
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return path


def write_json(path: Path, value: Any) -> Path:
    serialized = json.dumps(value, ensure_ascii=False, indent=2)
    return _atomic_write(path, serialized)


def write_model(path: Path, model: BaseModel) -> Path:
    return write_json(path, model.model_dump(mode="json"))


def write_text(path: Path, value: str) -> Path:
    return _atomic_write(path, value)


def write_bytes(path: Path, value: bytes) -> Path:
    return _atomic_write(path, value)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")
