from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts.package_agent_skills import package_skills


ROOT = Path(__file__).resolve().parents[1]


def test_product_package_contains_complete_canonical_skills(tmp_path):
    package = package_skills(tmp_path / "skills.zip")
    with ZipFile(package) as archive:
        names = set(archive.namelist())
        expected = {"hiqs-course-information", "hiqs-course-notes", "hiqs-notion-workspace", "hiqs-course-planning"}
        assert {Path(name).parts[0] for name in names} == expected
        for skill in expected:
            directory = ROOT / "skills" / skill
            assert (ROOT / ".agents/skills" / skill).samefile(directory)
            for path in directory.rglob("*"):
                if path.is_file():
                    name = path.relative_to(ROOT / "skills").as_posix()
                    assert archive.read(name) == path.read_bytes()


def test_skill_scripts_and_assets_survive_distribution_without_runtime_files(tmp_path):
    skills = tmp_path / "skills"
    skill = skills / "example"
    (skill / "scripts").mkdir(parents=True)
    (skill / "assets").mkdir()
    public = {
        "SKILL.md": b"---\nname: example\ndescription: Example workflow\n---\n",
        "scripts/helper.py": b"print('example')\n",
        "assets/schema.json": b'{"type": "object"}',
        "assets/template.bin": b"\x00\x01\x02",
    }
    for name, content in public.items():
        (skill / name).write_bytes(content)
    (skill / ".env").write_text("PRIVATE")
    (skill / "scripts/__pycache__").mkdir()
    (skill / "scripts/__pycache__/helper.pyc").write_bytes(b"cache")
    (tmp_path / "resources").mkdir()
    (tmp_path / "resources/information.json").write_text("PRIVATE")
    with ZipFile(package_skills(tmp_path / "skills.zip", skills_root=skills)) as archive:
        assert set(archive.namelist()) == {f"example/{name}" for name in public}
        for name, content in public.items():
            assert archive.read(f"example/{name}") == content


def test_invalid_skill_package_preserves_previous_output(tmp_path):
    skills = tmp_path / "skills"
    skill = skills / "example"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("Example")
    private = tmp_path / "private.txt"
    private.write_text("PRIVATE")
    (skill / "private.txt").symlink_to(private)
    output = tmp_path / "skills.zip"
    output.write_bytes(b"previous package")
    with pytest.raises(ValueError, match="symlinks"):
        package_skills(output, skills_root=skills)
    assert output.read_bytes() == b"previous package"


def test_package_output_cannot_be_inside_sources(tmp_path):
    with pytest.raises(ValueError, match="outside"):
        package_skills(tmp_path / "skills.zip", skills_root=tmp_path)
