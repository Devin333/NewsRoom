from __future__ import annotations

from pathlib import Path

import pytest

from framework.skills import (
    SkillMetadata,
    SkillPackage,
    SkillPackageLoader,
    SkillPackageValidator,
    SkillRiskLevel,
    SkillToolPermission,
    SkillValidationError,
    SkillValidationResult,
)


FIXTURES = Path("tests/fixtures/skills")


def test_validator_accepts_valid_package() -> None:
    package = SkillPackageLoader().load(FIXTURES / "valid-skill")
    result = SkillPackageValidator().validate_package(package)

    assert result.ok
    assert result.errors() == []


def test_validator_finds_missing_schema_files() -> None:
    package = SkillPackage(
        metadata=SkillMetadata(
            name="schema-missing",
            description="Missing schema fixture",
            path="tests/fixtures/skills/schema-missing",
            input_schema="schemas/missing-input.json",
            output_schema="schemas/missing-output.json",
        ),
        root_path="tests/fixtures/skills/valid-skill",
        skill_md_path="tests/fixtures/skills/valid-skill/SKILL.md",
    )

    result = SkillPackageValidator().validate_package(package)
    codes = {issue.code for issue in result.errors()}

    assert not result.ok
    assert "missing_input_schema_file" in codes
    assert "missing_output_schema_file" in codes


def test_validator_requires_high_risk_for_dangerous_tools() -> None:
    metadata = SkillMetadata(
        name="shell-skill",
        description="Dangerous tool fixture",
        path="skills/shell-skill",
        allowed_tools=[SkillToolPermission.SHELL],
        risk_level=SkillRiskLevel.MEDIUM,
    )

    result = SkillPackageValidator().validate_metadata(metadata)

    assert not result.ok
    assert [issue.code for issue in result.errors()] == ["dangerous_tool_without_high_risk"]


def test_validator_warns_when_high_risk_has_no_tools() -> None:
    metadata = SkillMetadata(
        name="high-risk",
        description="High risk fixture",
        path="skills/high-risk",
        risk_level=SkillRiskLevel.HIGH,
    )

    result = SkillPackageValidator().validate_metadata(metadata)

    assert not result.ok
    assert [issue.code for issue in result.errors()] == ["high_risk_without_tools"]


def test_validation_result_raise_if_invalid_raises() -> None:
    result = SkillValidationResult(ok=False, issues=[{"code": "missing_name", "message": "name is required"}])

    with pytest.raises(SkillValidationError):
        result.raise_if_invalid()
