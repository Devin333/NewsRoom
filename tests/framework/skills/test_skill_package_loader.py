from __future__ import annotations

from pathlib import Path

import pytest

from framework.skills import SkillCategory, SkillMetadataError, SkillPackageError, SkillPackageLoader


FIXTURES = Path("tests/fixtures/skills")


def test_loader_loads_valid_skill_package() -> None:
    package = SkillPackageLoader().load(FIXTURES / "valid-skill")

    assert package.metadata.name == "valid-skill"
    assert package.metadata.category == SkillCategory.EXTRACTION
    assert package.has_input_schema()
    assert package.has_output_schema()
    assert package.package_hash
    assert "schemas/input.schema.json" in package.manifest().schema_files


def test_loader_missing_skill_md_raises_package_error() -> None:
    with pytest.raises(SkillPackageError):
        SkillPackageLoader().load(FIXTURES / "not-a-skill")


def test_loader_missing_frontmatter_raises_metadata_error() -> None:
    with pytest.raises(SkillMetadataError):
        SkillPackageLoader().load(FIXTURES / "invalid-missing-frontmatter")


def test_parse_frontmatter_supports_multiline_yaml() -> None:
    content = """---
name: entity-extraction
description: >-
  multi line description
tags:
  - entity
  - extraction
---

# Body
"""

    data = SkillPackageLoader().parse_frontmatter(content, "memory")

    assert data["description"] == "multi line description"
    assert data["tags"] == ["entity", "extraction"]
