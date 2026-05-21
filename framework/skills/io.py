"""Skill input and output wrappers."""

from __future__ import annotations

from pydantic import BaseModel, Field

from framework.skills.context import SkillRunContext
from framework.skills.errors import SkillExecutionError
from framework.skills.result import SkillEvidence, SkillWarningDetail


class SkillInput(BaseModel):
    data: dict
    context: SkillRunContext

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def require(self, key: str):
        """Return a required value or raise SkillExecutionError."""
        if key not in self.data or self.data[key] is None:
            raise SkillExecutionError(f"required skill input field missing: {key}")
        return self.data[key]


class SkillOutput(BaseModel):
    data: dict
    raw: str | None = None
    evidence: list[SkillEvidence] = Field(default_factory=list)
    warnings: list[SkillWarningDetail] = Field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "SkillOutput":
        evidence = []
        raw_evidence = data.get("evidence") if isinstance(data, dict) else None
        if isinstance(raw_evidence, list):
            evidence = [
                item if isinstance(item, SkillEvidence) else SkillEvidence(**item)
                for item in raw_evidence
                if isinstance(item, dict) or isinstance(item, SkillEvidence)
            ]

        warnings = []
        raw_warnings = data.get("warnings") if isinstance(data, dict) else None
        if isinstance(raw_warnings, list):
            warnings = [
                item if isinstance(item, SkillWarningDetail) else SkillWarningDetail(**item)
                for item in raw_warnings
                if isinstance(item, dict) or isinstance(item, SkillWarningDetail)
            ]

        return cls(data=data, evidence=evidence, warnings=warnings)

    @classmethod
    def from_text(cls, text: str, output_key: str = "text") -> "SkillOutput":
        return cls(data={output_key: text}, raw=text)
