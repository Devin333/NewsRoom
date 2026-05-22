"""Skill execution result models."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class SkillRunStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    SKIPPED = "skipped"


class SkillFailureReason(str, Enum):
    NONE = "none"
    SKILL_NOT_FOUND = "skill_not_found"
    PACKAGE_INVALID = "package_invalid"
    INPUT_SCHEMA_INVALID = "input_schema_invalid"
    EXECUTION_FAILED = "execution_failed"
    OUTPUT_SCHEMA_INVALID = "output_schema_invalid"
    QUALITY_GATE_FAILED = "quality_gate_failed"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class SkillErrorDetail(BaseModel):
    code: str
    message: str
    field: str | None = None
    path: str | None = None
    detail: dict = Field(default_factory=dict)


class SkillWarningDetail(BaseModel):
    code: str
    message: str
    detail: dict = Field(default_factory=dict)


class SkillEvidence(BaseModel):
    source_id: str | None = None
    source_url: str | None = None
    span: str | None = None
    start_char: int | None = None
    end_char: int | None = None
    confidence: float | None = None


class SkillCost(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: int = 0


class SkillResult(BaseModel):
    skill_name: str
    version: str
    status: SkillRunStatus
    failure_reason: SkillFailureReason = SkillFailureReason.NONE

    output: dict = Field(default_factory=dict)

    errors: list[SkillErrorDetail] = Field(default_factory=list)
    warnings: list[SkillWarningDetail] = Field(default_factory=list)
    evidence: list[SkillEvidence] = Field(default_factory=list)

    quality_gate_results: list[dict] = Field(default_factory=list)
    trace: dict = Field(default_factory=dict)
    cost: SkillCost = Field(default_factory=SkillCost)

    def is_success(self) -> bool:
        return self.status == SkillRunStatus.SUCCESS and self.failure_reason == SkillFailureReason.NONE and not self.errors

    def add_error(
        self,
        code: str,
        message: str,
        field: str | None = None,
        path: str | None = None,
        detail: dict | None = None,
    ) -> None:
        self.errors.append(
            SkillErrorDetail(code=code, message=message, field=field, path=path, detail=detail or {})
        )

    def add_warning(self, code: str, message: str, detail: dict | None = None) -> None:
        self.warnings.append(SkillWarningDetail(code=code, message=message, detail=detail or {}))

    @classmethod
    def failed(
        cls,
        skill_name: str,
        version: str,
        reason: SkillFailureReason,
        code: str,
        message: str,
    ) -> "SkillResult":
        result = cls(skill_name=skill_name, version=version, status=SkillRunStatus.FAILED, failure_reason=reason)
        result.add_error(code=code, message=message)
        return result

    @classmethod
    def success(
        cls,
        skill_name: str,
        version: str,
        output: dict,
        evidence: list[SkillEvidence] | None = None,
        quality_gate_results: list[dict] | None = None,
        trace: dict | None = None,
        cost: SkillCost | None = None,
    ) -> "SkillResult":
        return cls(
            skill_name=skill_name,
            version=version,
            status=SkillRunStatus.SUCCESS,
            failure_reason=SkillFailureReason.NONE,
            output=output,
            evidence=evidence or [],
            quality_gate_results=quality_gate_results or [],
            trace=trace or {},
            cost=cost or SkillCost(),
        )
