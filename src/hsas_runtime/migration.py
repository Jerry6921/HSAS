"""Copy and verify legacy in-repository HSAS data without deleting it."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from dotenv import dotenv_values

from .paths import RuntimePaths, get_runtime_paths


ENV_TO_CONFIG = {
    "MOODLE_BASE_URL": "base_url",
    "MOODLE_LOGIN_URL": "login_url",
    "MOODLE_DASHBOARD_URL": "dashboard_url",
    "MOODLE_HEADLESS": "headless",
    "MOODLE_NAVIGATION_TIMEOUT_MS": "navigation_timeout_ms",
    "MOODLE_MAX_DOWNLOAD_BYTES": "max_download_bytes",
    "MOODLE_DOWNLOAD_CONCURRENCY": "download_concurrency",
}


class MigrationError(RuntimeError):
    """Raised when legacy data cannot be copied without ambiguity."""


@dataclass(frozen=True, slots=True)
class MigrationResult:
    destination: Path
    copied_files: int
    reused_files: int
    verified_files: int
    config_created: bool
    legacy_paths: tuple[Path, ...]


def migrate_legacy_data(
    legacy_root: Path,
    *,
    paths: RuntimePaths | None = None,
) -> MigrationResult:
    """Copy legacy resources/profile/config, verify hashes, and keep originals."""
    source_root = legacy_root.resolve()
    runtime = paths or get_runtime_paths()
    if runtime.data_dir == source_root or source_root in runtime.data_dir.parents:
        raise MigrationError("migration destination must be outside the code directory")

    pairs: list[tuple[Path, Path]] = []
    legacy_paths: list[Path] = []
    for source, destination in (
        (source_root / "src/resources", runtime.resources_dir),
        (source_root / ".moodle-profile", runtime.browser_profile_dir),
    ):
        if source.is_dir():
            legacy_paths.append(source)
            pairs.extend(_file_pairs(source, destination))

    config_text, selector_pair = _legacy_config(source_root, runtime)
    if selector_pair is not None:
        pairs.append(selector_pair)
    env_path = source_root / ".env"
    config_created = False
    if env_path.is_file():
        legacy_paths.append(env_path)
        if runtime.config_file.is_file():
            if runtime.config_file.read_text(encoding="utf-8") != config_text:
                raise MigrationError(
                    f"destination config already differs: {runtime.config_file}"
                )
        else:
            config_created = True

    reused = 0
    for source, destination in pairs:
        if destination.exists():
            if not destination.is_file() or destination.is_symlink():
                raise MigrationError(f"destination is not a regular file: {destination}")
            if _sha256(source) != _sha256(destination):
                raise MigrationError(
                    f"destination conflict; no files were changed: {destination}"
                )
            reused += 1

    runtime.create()
    copied_destinations: list[Path] = []
    copied = 0
    verified = 0
    try:
        for source, destination in pairs:
            if destination.exists():
                continue
            _atomic_copy(source, destination)
            copied_destinations.append(destination)
            copied += 1
        if config_created:
            _atomic_write_text(runtime.config_file, config_text)
            copied_destinations.append(runtime.config_file)

        for source, destination in pairs:
            if _sha256(source) != _sha256(destination):
                raise MigrationError(f"verification failed: {destination}")
            verified += 1
        if (
            config_created
            and runtime.config_file.read_text(encoding="utf-8") != config_text
        ):
            raise MigrationError(
                f"configuration verification failed: {runtime.config_file}"
            )

        report = {
            "schema_version": "1.0",
            "source_root": str(source_root),
            "destination": str(runtime.data_dir),
            "copied_files": copied,
            "reused_files": reused,
            "verified_files": verified,
            "legacy_paths_retained": [str(path) for path in legacy_paths],
        }
        _atomic_write_text(
            runtime.state_dir / "migration-report.json",
            json.dumps(report, ensure_ascii=False, indent=2),
        )
    except Exception as exc:
        for destination in reversed(copied_destinations):
            destination.unlink(missing_ok=True)
        if isinstance(exc, MigrationError):
            raise
        raise MigrationError(f"migration failed and new files were rolled back: {exc}") from exc
    return MigrationResult(
        destination=runtime.data_dir,
        copied_files=copied,
        reused_files=reused,
        verified_files=verified,
        config_created=config_created,
        legacy_paths=tuple(legacy_paths),
    )


def _file_pairs(source_root: Path, destination_root: Path) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    for source in sorted(source_root.rglob("*")):
        if source.is_symlink():
            raise MigrationError(f"legacy data contains unsupported symlink: {source}")
        if source.is_file():
            pairs.append((source, destination_root / source.relative_to(source_root)))
    return pairs


def _legacy_config(
    source_root: Path,
    runtime: RuntimePaths,
) -> tuple[str, tuple[Path, Path] | None]:
    values = dotenv_values(source_root / ".env")
    rows = ["[moodle]"]
    for environment_name, config_name in ENV_TO_CONFIG.items():
        raw = values.get(environment_name)
        if raw is None or not str(raw).strip():
            continue
        rows.append(f"{config_name} = {_toml_value(str(raw).strip())}")

    selector_pair: tuple[Path, Path] | None = None
    selector_value = values.get("MOODLE_SELECTOR_CONFIG")
    if selector_value:
        source = Path(str(selector_value))
        if not source.is_absolute():
            source = source_root / source
        public_default = source_root / "config/selectors.example.json"
        if source.is_file() and source.resolve() != public_default.resolve():
            destination = runtime.data_dir / "selectors.json"
            selector_pair = (source, destination)
            rows.append('selector_config = "selectors.json"')
    return "\n".join(rows) + "\n", selector_pair


def _toml_value(value: str) -> str:
    lowered = value.casefold()
    if lowered in {"true", "false"}:
        return lowered
    try:
        return str(int(value))
    except ValueError:
        return json.dumps(value, ensure_ascii=False)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=destination.parent, suffix=".migrate")
    os.close(descriptor)
    temporary = Path(name)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, suffix=".migrate")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
