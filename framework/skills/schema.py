"""Deprecated compatibility module. Use framework.skills.validation.schema instead."""

from framework.skills.validation.schema import SchemaValidationIssue, SchemaValidationResult, SkillSchemaValidator

__all__ = [
    "SchemaValidationIssue",
    "SchemaValidationResult",
    "SkillSchemaValidator",
]
