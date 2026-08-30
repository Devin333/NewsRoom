from __future__ import annotations

from tests.backend.foundation.skills._helpers import (
    REQUIRED_PACKAGE_FILES,
    SKILL_ROOT,
    skill_paths,
)


def test_skill_root_exists() -> None:
    assert SKILL_ROOT.is_dir()


def test_required_skill_packages_exist() -> None:
    for skill_path in skill_paths():
        assert skill_path.is_dir(), f"missing skill package: {skill_path.name}"


def test_each_skill_package_contains_required_files() -> None:
    for skill_path in skill_paths():
        for relative_path in REQUIRED_PACKAGE_FILES:
            path = skill_path / relative_path
            assert path.is_file(), f"{skill_path.name} missing {relative_path}"
            assert path.read_text(encoding="utf-8").strip(), f"{path} must not be empty"
