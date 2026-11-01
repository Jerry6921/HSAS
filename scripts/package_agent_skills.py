"""Package the product skills in skills/, including their scripts and assets."""

from __future__ import annotations

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZIP_DEFLATED


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "skills"


def package_skills(output: Path, *, skills_root: Path = SKILLS_ROOT) -> Path:
    skills_root = skills_root.resolve()
    if output.resolve().is_relative_to(skills_root):
        raise ValueError("Package output must be outside the skill source directory")
    directories = sorted(path.parent for path in skills_root.glob("*/SKILL.md"))
    if not directories:
        raise ValueError("No product skills found")
    files = []
    for directory in directories:
        if directory.is_symlink():
            raise ValueError(f"Skill source must not be a symlink: {directory.name}")
        for path in sorted(directory.rglob("*")):
            relative = path.relative_to(skills_root)
            if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
                continue
            if path.is_symlink():
                raise ValueError(f"Skill resources must not be symlinks: {relative}")
            if path.is_file() and path.suffix not in {".pyc", ".pyo"}:
                files.append((path, relative))
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as temporary:
        package = Path(temporary) / "skills.zip"
        with ZipFile(package, "w", ZIP_DEFLATED) as archive:
            for path, relative in files:
                archive.write(path, relative)
        package.replace(output)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(package_skills(args.output))
