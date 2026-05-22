"""Deprecated compatibility module. Use framework.skills.runtime.executor instead."""

from framework.skills.runtime.executor import LLMSkillExecutor, MockSkillExecutor, SkillExecutor

__all__ = [
    "SkillExecutor",
    "MockSkillExecutor",
    "LLMSkillExecutor",
]
