"""Deprecated compatibility module. Use framework.skills.core.errors instead."""

from framework.skills.core.errors import (
    SkillDuplicateError,
    SkillError,
    SkillExecutionError,
    SkillMetadataError,
    SkillNotFoundError,
    SkillPackageError,
    SkillValidationError,
)

__all__ = [
    "SkillError",
    "SkillMetadataError",
    "SkillPackageError",
    "SkillNotFoundError",
    "SkillValidationError",
    "SkillDuplicateError",
    "SkillExecutionError",
]
