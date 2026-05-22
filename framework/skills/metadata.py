"""Deprecated compatibility module. Use framework.skills.core.metadata instead."""

from framework.skills.core.metadata import (
    SkillCapability,
    SkillCategory,
    SkillMetadata,
    SkillRiskLevel,
    SkillStatus,
    SkillToolPermission,
    SkillVersion,
)

__all__ = [
    "SkillMetadata",
    "SkillCapability",
    "SkillVersion",
    "SkillRiskLevel",
    "SkillStatus",
    "SkillCategory",
    "SkillToolPermission",
]
