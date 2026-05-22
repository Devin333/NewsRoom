"""Deprecated compatibility module. Use framework.skills.package.validator instead."""

from framework.skills.package.validator import SkillPackageValidator, SkillValidationIssue, SkillValidationResult

__all__ = [
    "SkillPackageValidator",
    "SkillValidationIssue",
    "SkillValidationResult",
]
