"""Clone and transactionally apply the trusted HSAS Git release."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import tomllib
from typing import Callable, Sequence

from hsas_runtime import get_runtime_paths


PROJECT_NAME = "hku-study-assistance-system"
UPDATE_REPOSITORY = "https://github.com/Jerry6921/HSAS"
UPDATE_BRANCH = "main"
MANIFEST_NAME = "update-manifest.json"

# User/session state is never copied from Git and never deleted by the updater.
PROTECTED_PATHS = (
    PurePosixPath("src/resources"),
    PurePosixPath(".env"),
    PurePosixPath(".moodle-profile"),
    PurePosixPath(".venv"),
    PurePosixPath(".git"),
    PurePosixPath("config/selectors.local.json"),
)


class UpdateError(RuntimeError):
    """Raised when an update cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class UpdateResult:
    commit: str
    copied_files: int
    removed_files: int
    dry_run: bool
    dependencies_installed: bool


CommandRunner = Callable[
    [Sequence[str], Path | None],
    subprocess.CompletedProcess[str],
]


def update_installation(
    project_root: Path,
    *,
    dry_run: bool = False,
    runner: CommandRunner | None = None,
    repository: str = UPDATE_REPOSITORY,
    branch: str = UPDATE_BRANCH,
    install_dependencies: bool = True,
    state_dir: Path | None = None,
) -> UpdateResult:
    """Update code from the trusted release while preserving local state."""
    root = project_root.resolve()
    updater_state = (state_dir or get_runtime_paths().state_dir).resolve()
    manifest_path = updater_state / MANIFEST_NAME
    _validate_project(root)
    execute = runner or _run

    with tempfile.TemporaryDirectory(prefix="hsas-update-") as temporary:
        temporary_root = Path(temporary)
        checkout = temporary_root / "checkout"
        _execute(
            execute,
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                branch,
                "--single-branch",
                "--",
                repository,
                str(checkout),
            ],
            cwd=None,
            action="clone the HSAS release",
        )
        _validate_release(checkout)
        commit = _execute(
            execute,
            ["git", "rev-parse", "HEAD"],
            cwd=checkout,
            action="resolve the release commit",
        ).stdout.strip()
        incoming = _tracked_release_files(checkout, execute)
        previous = _read_manifest(manifest_path)
        old_managed = {
            PurePosixPath(value)
            for value in previous.get("managed_files", [])
            if isinstance(value, str) and _is_safe_relative(PurePosixPath(value))
        }
        incoming_paths = set(incoming)
        obsolete = sorted(
            path
            for path in old_managed - incoming_paths
            if not _is_protected(path)
        )
        changed = sorted(
            path
            for path, source in incoming.items()
            if not _same_file(source, root / Path(path))
        )
        removable = [path for path in obsolete if (root / Path(path)).is_file()]

        if dry_run:
            return UpdateResult(
                commit=commit,
                copied_files=len(changed),
                removed_files=len(removable),
                dry_run=True,
                dependencies_installed=False,
            )

        backup = temporary_root / "backup"
        touched = sorted(set(changed) | set(removable))
        existed = _backup_files(root, backup, touched)
        manifest_backup = backup / MANIFEST_NAME
        manifest_existed = manifest_path.is_file()
        if manifest_existed:
            manifest_backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(manifest_path, manifest_backup)

        try:
            for path in removable:
                (root / Path(path)).unlink()
            for path in changed:
                _atomic_copy(incoming[path], root / Path(path))
            if install_dependencies:
                _execute(
                    execute,
                    [sys.executable, "-m", "pip", "install", "-e", str(root)],
                    cwd=root,
                    action="install the updated HSAS package",
                )
            updater_state.mkdir(parents=True, exist_ok=True)
            _write_manifest(
                manifest_path,
                {
                    "schema_version": "1.0",
                    "repository": repository,
                    "branch": branch,
                    "commit": commit,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "managed_files": [path.as_posix() for path in sorted(incoming)],
                    "protected_paths": [path.as_posix() for path in PROTECTED_PATHS],
                },
            )
        except Exception as exc:
            _restore_files(root, backup, touched, existed)
            if manifest_existed:
                _atomic_copy(manifest_backup, manifest_path)
            else:
                manifest_path.unlink(missing_ok=True)
            if isinstance(exc, UpdateError):
                raise
            raise UpdateError(f"update failed and code was rolled back: {exc}") from exc

        return UpdateResult(
            commit=commit,
            copied_files=len(changed),
            removed_files=len(removable),
            dry_run=False,
            dependencies_installed=install_dependencies,
        )


def _validate_project(root: Path) -> None:
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        raise UpdateError(f"not an HSAS project root: {root}")
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project_name = data["project"]["name"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise UpdateError(f"invalid pyproject.toml: {exc}") from exc
    if project_name != PROJECT_NAME:
        raise UpdateError(f"unexpected project name: {project_name}")


def _validate_release(checkout: Path) -> None:
    _validate_project(checkout)
    required = (
        checkout / "src/command.py",
        checkout / "src/updator/service.py",
    )
    missing = [
        path.relative_to(checkout).as_posix()
        for path in required
        if not path.is_file()
    ]
    if missing:
        raise UpdateError(
            "release is not updater-compatible; missing " + ", ".join(missing)
        )


def _tracked_release_files(
    checkout: Path,
    runner: CommandRunner,
) -> dict[PurePosixPath, Path]:
    result = _execute(
        runner,
        ["git", "ls-files", "-z"],
        cwd=checkout,
        action="list release files",
    )
    files: dict[PurePosixPath, Path] = {}
    for value in result.stdout.split("\0"):
        if not value:
            continue
        relative = PurePosixPath(value)
        source = checkout / Path(relative)
        if not _is_safe_relative(relative) or _is_protected(relative):
            continue
        if source.is_symlink():
            raise UpdateError(f"release contains unsupported symlink: {relative}")
        if not source.is_file():
            raise UpdateError(f"tracked release file is missing: {relative}")
        files[relative] = source
    return files


def _is_safe_relative(path: PurePosixPath) -> bool:
    return bool(path.parts) and not path.is_absolute() and ".." not in path.parts


def _is_protected(path: PurePosixPath) -> bool:
    if not _is_safe_relative(path):
        return True
    return any(path == value or value in path.parents for value in PROTECTED_PATHS)


def _same_file(source: Path, destination: Path) -> bool:
    return (
        destination.is_file()
        and not destination.is_symlink()
        and source.stat().st_size == destination.stat().st_size
        and source.read_bytes() == destination.read_bytes()
    )


def _backup_files(
    root: Path,
    backup: Path,
    paths: list[PurePosixPath],
) -> set[PurePosixPath]:
    existed: set[PurePosixPath] = set()
    for path in paths:
        source = root / Path(path)
        if source.is_file() and not source.is_symlink():
            destination = backup / Path(path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            existed.add(path)
        elif source.exists() or source.is_symlink():
            raise UpdateError(f"managed path is not a regular file: {path}")
    return existed


def _restore_files(
    root: Path,
    backup: Path,
    paths: list[PurePosixPath],
    existed: set[PurePosixPath],
) -> None:
    for path in paths:
        destination = root / Path(path)
        if path in existed:
            _atomic_copy(backup / Path(path), destination)
        else:
            destination.unlink(missing_ok=True)


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".update",
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _read_manifest(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateError(f"invalid update manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise UpdateError("invalid update manifest: expected an object")
    return value


def _write_manifest(path: Path, value: dict[str, object]) -> None:
    descriptor, name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".update",
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _execute(
    runner: CommandRunner,
    command: Sequence[str],
    *,
    cwd: Path | None,
    action: str,
) -> subprocess.CompletedProcess[str]:
    try:
        result = runner(command, cwd)
    except OSError as exc:
        raise UpdateError(f"cannot {action}: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise UpdateError(f"cannot {action}: {detail or 'command failed'}")
    return result


def _run(
    command: Sequence[str],
    cwd: Path | None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
