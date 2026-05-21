"""Structured exceptions for the framework skill system."""

from __future__ import annotations


class SkillError(Exception):
    """Base exception for framework skill system."""


class SkillMetadataError(SkillError):
    """Raised when SKILL.md frontmatter or metadata is invalid."""


class SkillPackageError(SkillError):
    """Raised when a skill package cannot be loaded."""


class SkillNotFoundError(SkillError):
    """Raised when a skill cannot be found in registry."""


class SkillValidationError(SkillError):
    """Raised when skill package validation fails."""


class SkillDuplicateError(SkillError):
    """Raised when duplicate skill names or aliases are discovered."""


class SkillExecutionError(SkillError):
    """Raised when skill execution cannot continue."""
