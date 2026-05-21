from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from framework.skills import SkillMetadataError, SkillScanner


FIXTURES = Path("tests/fixtures/skills")
VALID_FIXTURE = FIXTURES / "valid-skill"


def test_scanner_skips_non_skill_directories(tmp_path: Path) -> None:
    skill_dir = tmp_path / "valid-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text((VALID_FIXTURE / "SKILL.md").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "not-a-skill").mkdir()
    (tmp_path / "not-a-skill" / "README.md").write_text("# Not a skill\n", encoding="utf-8")

    scanner = SkillScanner()

    names = [metadata.name for metadata in scanner.scan(tmp_path)]

    assert names == ["valid-skill"]
    assert scanner.is_skill_dir(skill_dir)
    assert not scanner.is_skill_dir(tmp_path / "not-a-skill")


def test_scanner_loads_packages(tmp_path: Path) -> None:
    shutil.copytree(VALID_FIXTURE, tmp_path / "valid-skill")

    packages = SkillScanner().scan_packages(tmp_path)

    assert [package.metadata.name for package in packages] == ["valid-skill"]
    assert packages[0].raw_skill_md.startswith("---")


def test_scanner_surfaces_invalid_skill_metadata() -> None:
    with pytest.raises(SkillMetadataError):
        SkillScanner().scan(FIXTURES)
