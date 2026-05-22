"""Deprecated compatibility module. Use framework.skills.tracing.trace instead."""

from framework.skills.tracing.trace import SkillTraceEvent, SkillTraceRecorder

__all__ = [
    "SkillTraceEvent",
    "SkillTraceRecorder",
]
