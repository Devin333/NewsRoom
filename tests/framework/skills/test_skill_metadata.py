from __future__ import annotations

import pytest

from framework.skills import (
    SkillCategory,
    SkillMetadata,
    SkillMetadataError,
    SkillRiskLevel,
    SkillStatus,
    SkillToolPermission,
    SkillVersion,
)


def test_skill_version_parse_success() -> None:
    version = SkillVersion.parse("1.2.3")

    assert version.major == 1
    assert version.minor == 2
    assert version.patch == 3
    assert str(version) == "1.2.3"


def test_skill_version_parse_rejects_incomplete_version() -> None:
    with pytest.raises(SkillMetadataError):
        SkillVersion.parse("1.2")


def test_skill_metadata_helpers() -> None:
    metadata = SkillMetadata(
        name=" Entity-Extraction ",
        version="1.0.0",
        description="Extract entities",
        category=SkillCategory.EXTRACTION,
        tags=["Entity", "news"],
        path="skills/entity-extraction",
        allowed_tools=[SkillToolPermission.SCHEMA_VALIDATOR],
        risk_level=SkillRiskLevel.LOW,
        status=SkillStatus.ACTIVE,
    )

    assert metadata.canonical_name() == "entity-extraction"
    assert metadata.is_active()
    assert metadata.allows_tool("schema_validator")
    assert not metadata.allows_tool("shell")
    assert metadata.matches_tag("entity")
    assert metadata.matches_category("extraction")
