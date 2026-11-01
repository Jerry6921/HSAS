from pathlib import Path

import pytest

from scripts.install_agent_skills import default_destination, install_skills


def make_skill(root, name="hiqs-example", content="Version one"):
    directory = root / name
    (directory / "scripts").mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Example\n---\n{content}\n")
    (directory / "scripts/helper.py").write_text("print('ready')\n")
    (directory / "scripts/helper.py").chmod(0o755)
    return directory


def test_install_update_readback_backup_and_unrelated_skill_preservation(tmp_path):
    source = tmp_path / "repo/skills"
    skill = make_skill(source)
    destination = tmp_path / "agent/skills"
    unrelated = make_skill(destination, "another-skill", "Keep me")
    first = install_skills(destination, skills_root=source)
    target = destination / "hiqs-example"
    assert first["status"] == "verified"
    assert (target / "SKILL.md").read_bytes() == (skill / "SKILL.md").read_bytes()
    assert (target / "scripts/helper.py").stat().st_mode & 0o111
    again = install_skills(destination, skills_root=source)
    assert again["skills"][0]["status"] == "unchanged"
    (target / "stale.md").write_text("Keep in backup")
    (skill / "SKILL.md").write_text("Version two")
    updated = install_skills(destination, skills_root=source)
    backup = Path(updated["skills"][0]["backup"])
    assert (backup / "stale.md").read_text() == "Keep in backup"
    assert not (target / "stale.md").exists()
    assert (target / "SKILL.md").read_text() == "Version two"
    assert "Keep me" in (unrelated / "SKILL.md").read_text()


def test_failed_replacement_rolls_back_previous_installs(tmp_path, monkeypatch):
    source, destination = tmp_path / "repo/skills", tmp_path / "agent/skills"
    for name in ("hiqs-a", "hiqs-b"):
        make_skill(source, name)
    install_skills(destination, skills_root=source)
    for name in ("hiqs-a", "hiqs-b"):
        (source / name / "SKILL.md").write_text("Updated")
    original = Path.replace
    def fail_second(self, target):
        if "unpacked" in self.parts and self.name == "hiqs-b":
            raise OSError("Simulated replacement failure")
        return original(self, target)
    monkeypatch.setattr(Path, "replace", fail_second)
    with pytest.raises(OSError, match="Simulated"):
        install_skills(destination, skills_root=source)
    for name in ("hiqs-a", "hiqs-b"):
        assert "Version one" in (destination / name / "SKILL.md").read_text()


def test_source_destination_overlap_is_rejected(tmp_path):
    source = tmp_path / "skills"
    make_skill(source)
    for destination in (source, source / "installed", tmp_path):
        with pytest.raises(ValueError, match="overlap"):
            install_skills(destination, skills_root=source)


def test_destination_follows_codex_home_without_changing_it(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "custom-codex"))
    assert default_destination() == tmp_path / "custom-codex/skills"
