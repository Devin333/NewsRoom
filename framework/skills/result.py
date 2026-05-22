"""Deprecated compatibility module. Use framework.skills.core.result instead."""

from framework.skills.core.result import (
    SkillCost,
    SkillErrorDetail,
    SkillEvidence,
    SkillFailureReason,
    SkillResult,
    SkillRunStatus,
    SkillWarningDetail,
)

__all__ = [
    "SkillRunStatus",
    "SkillFailureReason",
    "SkillErrorDetail",
    "SkillWarningDetail",
    "SkillEvidence",
    "SkillCost",
    "SkillResult",
]
