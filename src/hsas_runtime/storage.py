"""Generic atomic JSON/text/binary persistence for all HSAS applications."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any

from pydantic import BaseModel


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
