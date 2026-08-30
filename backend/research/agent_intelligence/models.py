from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from backend.foundation import PrimitiveModel, normalize_key
from backend.research.domain.common import require_text, unique_texts


DEFAULT_AGENT_TASK_TYPES = {
    "web_agent",
    "code_agent",
    "tool_use",
    "memory_agent",
    "multi_agent_coordination",
    "self_evolving_skill",
    "reader_repair",
    "paper_analysis",
}


class AgentSkillToolIntelligence(PrimitiveModel):
    intelligence_id: str
    task_type: str
    representative_papers: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    benchmarks: list[str] = Field(default_factory=list)
    high_scoring_skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    failure_modes: list[str] = Field(default_factory=list)
    evidence_refs: list[str]
    confidence: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("intelligence_id", "task_type")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "agent intelligence fields")

    @field_validator("confidence")
    @classmethod
    def _bounded_confidence(cls, value: float) -> float:
        numeric = float(value)
        if numeric < 0.0 or numeric > 1.0:
            raise ValueError("agent intelligence confidence must be between 0 and 1")
        return numeric

    @model_validator(mode="after")
    def _normalize(self) -> "AgentSkillToolIntelligence":
        object.__setattr__(self, "task_type", normalize_key(self.task_type))
        for field_name in (
            "representative_papers",
            "methods",
            "benchmarks",
            "high_scoring_skills",
            "tools",
            "failure_modes",
            "evidence_refs",
        ):
            object.__setattr__(self, field_name, unique_texts(getattr(self, field_name)))
        if not self.evidence_refs:
            raise ValueError("agent intelligence requires evidence refs")
        return self

    @property
    def mutates_active_skill(self) -> bool:
        return bool(self.metadata.get("active_skill_mutation"))


def is_registered_agent_task(task_type: str, registry: set[str] | None = None) -> bool:
    return normalize_key(task_type) in (registry or DEFAULT_AGENT_TASK_TYPES)


__all__ = ["AgentSkillToolIntelligence", "DEFAULT_AGENT_TASK_TYPES", "is_registered_agent_task"]
