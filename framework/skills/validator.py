"""Skill package validation."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from framework.skills.errors import SkillValidationError
from framework.skills.metadata import (
    SkillCategory,
    SkillMetadata,
    SkillRiskLevel,
    SkillToolPermission,
    SkillVersion,
)
from framework.skills.package import SkillPackage


DANGEROUS_TOOLS = {
    SkillToolPermission.SHELL,
    SkillToolPermission.FILESYSTEM_WRITE,
    SkillToolPermission.DATABASE_WRITE,
    SkillToolPermission.NETWORK_POST,
}


class SkillValidationIssue(BaseModel):
    code: str
    message: str
    severity: str = "error"
    path: str | None = None
    field: str | None = None


class SkillValidationResult(BaseModel):
    ok: bool
    issues: list[SkillValidationIssue] = Field(default_factory=list)

    def errors(self) -> list[SkillValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    def warnings(self) -> list[SkillValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    def raise_if_invalid(self) -> None:
        """Raise SkillValidationError if not ok."""
        if self.ok:
            return
        codes = ", ".join(issue.code for issue in self.errors())
        raise SkillValidationError(f"skill validation failed: {codes}")


class SkillPackageValidator:
    def validate_package(self, package: SkillPackage) -> SkillValidationResult:
        issues = [
            *self.validate_metadata(package.metadata).issues,
            *self.validate_required_files(package),
            *self.validate_name_matches_directory(package),
        ]
        return SkillValidationResult(ok=not _has_errors(issues), issues=issues)

    def validate_metadata(self, metadata: SkillMetadata) -> SkillValidationResult:
        issues: list[SkillValidationIssue] = []
        if not metadata.name.strip():
            issues.append(_issue("missing_name", "skill name is required", field="name"))
        if not metadata.description.strip():
            issues.append(_issue("missing_description", "skill description is required", field="description"))

        try:
            SkillVersion.parse(metadata.version)
        except Exception:
            issues.append(_issue("invalid_version", "skill version must use MAJOR.MINOR.PATCH", field="version"))

        if not isinstance(metadata.category, SkillCategory):
            issues.append(_issue("invalid_category", "skill category is invalid", field="category"))
        if not isinstance(metadata.risk_level, SkillRiskLevel):
            issues.append(_issue("invalid_risk_level", "skill risk level is invalid", field="risk_level"))

        issues.extend(self.validate_tool_permissions(metadata))
        return SkillValidationResult(ok=not _has_errors(issues), issues=issues)

    def validate_required_files(self, package: SkillPackage) -> list[SkillValidationIssue]:
        issues: list[SkillValidationIssue] = []
        if not package.skill_md().is_file():
            issues.append(_issue("missing_skill_md", "SKILL.md is required", path=str(package.skill_md())))
        if package.metadata.input_schema and not package.has_input_schema():
            issues.append(
                _issue(
                    "missing_input_schema_file",
                    "input schema file does not exist",
                    path=str(package.resolve_relative_path(package.metadata.input_schema)),
                    field="input_schema",
                )
            )
        if package.metadata.output_schema and not package.has_output_schema():
            issues.append(
                _issue(
                    "missing_output_schema_file",
                    "output schema file does not exist",
                    path=str(package.resolve_relative_path(package.metadata.output_schema)),
                    field="output_schema",
                )
            )
        return issues

    def validate_tool_permissions(self, metadata: SkillMetadata) -> list[SkillValidationIssue]:
        issues: list[SkillValidationIssue] = []
        if metadata.risk_level == SkillRiskLevel.HIGH and not metadata.allowed_tools:
            issues.append(
                _issue(
                    "high_risk_without_tools",
                    "high risk skills must declare allowed tools",
                    field="allowed_tools",
                )
            )

        dangerous = [tool for tool in metadata.allowed_tools if tool in DANGEROUS_TOOLS]
        if dangerous and metadata.risk_level != SkillRiskLevel.HIGH:
            issues.append(
                _issue(
                    "dangerous_tool_without_high_risk",
                    "dangerous tools require high risk level",
                    field="risk_level",
                )
            )
        return issues

    def validate_name_matches_directory(self, package: SkillPackage) -> list[SkillValidationIssue]:
        directory_name = Path(package.root_path).name.lower()
        if package.metadata.canonical_name() == directory_name:
            return []
        return [
            SkillValidationIssue(
                code="name_directory_mismatch",
                message="skill name should match package directory name",
                severity="warning",
                path=package.root_path,
                field="name",
            )
        ]


def _issue(code: str, message: str, *, path: str | None = None, field: str | None = None) -> SkillValidationIssue:
    return SkillValidationIssue(code=code, message=message, path=path, field=field)


def _has_errors(issues: list[SkillValidationIssue]) -> bool:
    return any(issue.severity == "error" for issue in issues)
