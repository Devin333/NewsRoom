from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from framework.skills import (
    SkillCategory,
    SkillDuplicateError,
    SkillMetadata,
    SkillNotFoundError,
    SkillRegistry,
    SkillStatus,
    SkillToolPermission,
)


FIXTURES = Path("tests/fixtures/skills")


def test_registry_supports_name_alias_category_and_tag_queries(tmp_path: Path) -> None:
    shutil.copytree(FIXTURES / "valid-skill", tmp_path / "valid-skill")
    registry = SkillRegistry()
    registry.scan(tmp_path, load_packages=True)

    assert registry.get("valid-skill").name == "valid-skill"  # type: ignore[union-attr]
    assert registry.get("entity-extract").name == "valid-skill"  # type: ignore[union-attr]
    assert registry.require("valid-skill").category == SkillCategory.EXTRACTION
    assert [item.name for item in registry.find_by_category("extraction")] == ["valid-skill"]
    assert [item.name for item in registry.find_by_tag("ENTITY")] == ["valid-skill"]
    assert [item.name for item in registry.find_by_allowed_tool("schema_validator")] == ["valid-skill"]
    assert registry.get_package("entity-extract") is not None


def test_registry_get_returns_none_and_require_raises() -> None:
    registry = SkillRegistry()

    assert registry.get("missing") is None
    with pytest.raises(SkillNotFoundError):
        registry.require("missing")


def test_registry_duplicate_name_raises() -> None:
    registry = SkillRegistry()
    metadata = SkillMetadata(name="dupe", description="one", path="skills/dupe")

    registry.register(metadata)

    with pytest.raises(SkillDuplicateError):
        registry.register(SkillMetadata(name="DUPE", description="two", path="skills/dupe-2"))


def test_registry_duplicate_alias_raises() -> None:
    registry = SkillRegistry()
    registry.register(SkillMetadata(name="one", description="one", path="skills/one", aliases=["shared"]))

    with pytest.raises(SkillDuplicateError):
        registry.register(SkillMetadata(name="two", description="two", path="skills/two", aliases=["SHARED"]))


def test_registry_hides_disabled_by_default() -> None:
    registry = SkillRegistry()
    registry.register(
        SkillMetadata(
            name="disabled",
            description="disabled",
            path="skills/disabled",
            status=SkillStatus.DISABLED,
            allowed_tools=[SkillToolPermission.SCHEMA_VALIDATOR],
        )
    )

    assert registry.list_all() == []
    assert [item.name for item in registry.list_all(include_disabled=True)] == ["disabled"]
    assert registry.describe()["disabled"] == 1
