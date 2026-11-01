"""Install the local HIQS product Skills after development checks pass."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from uuid import uuid4
from zipfile import ZipFile

try:
    from scripts.package_agent_skills import SKILLS_ROOT, package_skills
except ModuleNotFoundError:  # direct script invocation
    from package_agent_skills import SKILLS_ROOT, package_skills


def default_destination() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "skills"


def _contents(directory: Path) -> dict[str, str] | None:
    if directory.is_symlink() or not directory.is_dir():
        return None
    result = {}
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
            continue
        if path.is_symlink():
            return None
        if path.is_file() and path.suffix not in {".pyc", ".pyo"}:
            result[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def install_skills(destination: Path | None = None, *, skills_root: Path = SKILLS_ROOT) -> dict:
    destination = (destination or default_destination()).expanduser().absolute()
    skills_root = skills_root.resolve()
    if destination.resolve().is_relative_to(skills_root) or skills_root.is_relative_to(destination.resolve()):
        raise ValueError("Installation and source directories must not overlap")
    destination.mkdir(parents=True, exist_ok=True)
    backups = destination.parent / "hiqs-skill-backups" / uuid4().hex
    with (destination / ".hiqs-install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with TemporaryDirectory(dir=destination.parent, prefix=".hiqs-install-") as temporary:
            staging = Path(temporary)
            package = package_skills(staging / "skills.zip", skills_root=skills_root)
            with ZipFile(package) as archive:
                archive.extractall(staging / "unpacked")
                for member in archive.infolist():
                    (staging / "unpacked" / member.filename).chmod((member.external_attr >> 16) & 0o777)
            directories = sorted((staging / "unpacked").iterdir())
            expected = {p.name: _contents(p) for p in directories}
            changed: list[tuple[Path, Path | None]] = []
            reports = []
            try:
                for source in directories:
                    target = destination / source.name
                    if _contents(target) == expected[source.name]:
                        reports.append({"name": source.name, "status": "unchanged", "path": str(target)})
                        continue
                    backup = None
                    if target.exists() or target.is_symlink():
                        backups.mkdir(parents=True, exist_ok=True)
                        backup = backups / source.name
                        target.replace(backup)
                    changed.append((target, backup))
                    source.replace(target)
                    if _contents(target) != expected[source.name]:
                        raise OSError(f"Installed Skill readback failed: {source.name}")
                    reports.append({"name": source.name, "status": "installed", "path": str(target),
                                    "backup": str(backup) if backup else None})
            except Exception:
                for target, backup in reversed(changed):
                    if target.is_symlink() or target.is_file():
                        target.unlink()
                    elif target.exists():
                        shutil.rmtree(target)
                    if backup is not None:
                        backup.replace(target)
                raise
            return {"status": "verified", "destination": str(destination), "skills": reports}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=None)
    args = parser.parse_args()
    print(json.dumps(install_skills(args.destination), ensure_ascii=False, indent=2))
