from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from business.foundation.primitives import PrimitiveModel, SourceRef, build_stable_id, ensure_utc


class BusinessProvenance(PrimitiveModel):
    run_id: str | None = None
    workflow_id: str | None = None
    step_id: str | None = None
    trace_ref: SourceRef | None = None
    manifest_ref: SourceRef | None = None
    source_refs: list[SourceRef] = Field(default_factory=list)
    evidence_refs: list[SourceRef] = Field(default_factory=list)
    upstream_object_refs: list[SourceRef] = Field(default_factory=list)
    policy_profile_id: str | None = None
    policy_profile_version: str | None = None
    policy_snapshot_ref: SourceRef | None = None
    created_by: str = "system"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _normalize_created_at(self) -> "BusinessProvenance":
        object.__setattr__(self, "created_at", ensure_utc(self.created_at) or self.created_at)
        return self


class BusinessQualityCheck(PrimitiveModel):
    check_id: str
    check_type: str
    passed: bool
    severity: str = "warning"
    reason: str = ""
    expected: dict[str, Any] = Field(default_factory=dict)
    observed: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[SourceRef] = Field(default_factory=list)
    trace_ref: SourceRef | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("check_id", "check_type", "severity")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("quality check text fields must be non-empty")
        return text

    @classmethod
    def create(
        cls,
        check_type: str,
        *,
        passed: bool,
        severity: str = "warning",
        reason: str = "",
        expected: dict[str, Any] | None = None,
        observed: dict[str, Any] | None = None,
        evidence_refs: list[SourceRef] | None = None,
        trace_ref: SourceRef | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "BusinessQualityCheck":
        return cls(
            check_id=build_stable_id("bqc", check_type, passed, severity, reason, observed or {}),
            check_type=check_type,
            passed=passed,
            severity=severity,
            reason=reason,
            expected=expected or {},
            observed=observed or {},
            evidence_refs=evidence_refs or [],
            trace_ref=trace_ref,
            metadata=metadata or {},
        )


class BusinessQualitySnapshot(PrimitiveModel):
    status: str = "unchecked"
    score: float | None = None
    confidence: float | None = None
    checks: list[BusinessQualityCheck] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_tags: list[str] = Field(default_factory=list)
    requires_review: bool = False
    review_reason: str | None = None
    evaluated_at: datetime | None = None

    @field_validator("score", "confidence")
    @classmethod
    def _optional_unit_interval(cls, value: float | None) -> float | None:
        if value is None:
            return None
        numeric = float(value)
        if not 0.0 <= numeric <= 1.0:
            raise ValueError("quality snapshot score fields must be between 0 and 1")
        return round(numeric, 4)

    @model_validator(mode="after")
    def _derive_status(self) -> "BusinessQualitySnapshot":
        object.__setattr__(self, "evaluated_at", ensure_utc(self.evaluated_at))
        if self.status != "unchecked":
            return self
        if not self.checks:
            return self
        if any(not check.passed and check.severity in {"error", "block"} for check in self.checks):
            object.__setattr__(self, "status", "failed")
        elif any(not check.passed for check in self.checks):
            object.__setattr__(self, "status", "warning")
        else:
            object.__setattr__(self, "status", "passed")
        return self


class BusinessFeedbackEvent(PrimitiveModel):
    feedback_id: str
    target_object_type: str
    target_object_id: str | None = None
    target_layer: str | None = None
    board_type: str | None = None
    feedback_type: str
    severity: str
    observed: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)
    error_tags: list[str] = Field(default_factory=list)
    evidence_refs: list[SourceRef] = Field(default_factory=list)
    trace_ref: SourceRef | None = None
    manifest_ref: SourceRef | None = None
    related_policy_profile_id: str | None = None
    related_policy_profile_version: str | None = None
    status: str = "open"
    created_by: str = "system"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("feedback_id", "target_object_type", "feedback_type", "severity", "status")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("feedback event text fields must be non-empty")
        return text

    @model_validator(mode="after")
    def _normalize_datetimes(self) -> "BusinessFeedbackEvent":
        object.__setattr__(self, "created_at", ensure_utc(self.created_at) or self.created_at)
        object.__setattr__(self, "resolved_at", ensure_utc(self.resolved_at))
        return self

    @classmethod
    def create(
        cls,
        *,
        target_object_type: str,
        feedback_type: str,
        severity: str = "warning",
        target_object_id: str | None = None,
        target_layer: str | None = None,
        board_type: str | None = None,
        observed: dict[str, Any] | None = None,
        expected: dict[str, Any] | None = None,
        error_tags: list[str] | None = None,
        evidence_refs: list[SourceRef] | None = None,
        trace_ref: SourceRef | None = None,
        manifest_ref: SourceRef | None = None,
        related_policy_profile_id: str | None = None,
        related_policy_profile_version: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "BusinessFeedbackEvent":
        return cls(
            feedback_id=build_stable_id(
                "fb",
                target_object_type,
                target_object_id or "",
                board_type or "",
                feedback_type,
                observed or {},
            ),
            target_object_type=target_object_type,
            target_object_id=target_object_id,
            target_layer=target_layer,
            board_type=board_type,
            feedback_type=feedback_type,
            severity=severity,
            observed=observed or {},
            expected=expected or {},
            error_tags=error_tags or [],
            evidence_refs=evidence_refs or [],
            trace_ref=trace_ref,
            manifest_ref=manifest_ref,
            related_policy_profile_id=related_policy_profile_id,
            related_policy_profile_version=related_policy_profile_version,
            metadata=metadata or {},
        )


class BusinessFeedbackLink(PrimitiveModel):
    feedback_id: str
    feedback_type: str
    severity: str
    status: str

    @classmethod
    def from_event(cls, event: BusinessFeedbackEvent) -> "BusinessFeedbackLink":
        return cls(
            feedback_id=event.feedback_id,
            feedback_type=event.feedback_type,
            severity=event.severity,
            status=event.status,
        )


class BusinessPolicyProfile(PrimitiveModel):
    profile_id: str
    profile_type: str
    version: str
    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    based_on_feedback_ids: list[str] = Field(default_factory=list)
    based_on_run_ids: list[str] = Field(default_factory=list)
    based_on_manifest_refs: list[SourceRef] = Field(default_factory=list)
    status: str = "active"
    activation_rule: dict[str, Any] = Field(default_factory=dict)
    rollback_ref: SourceRef | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    activated_at: datetime | None = None
    deprecated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("profile_id", "profile_type", "version", "name", "status")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("policy profile text fields must be non-empty")
        return text

    @model_validator(mode="after")
    def _normalize_datetimes(self) -> "BusinessPolicyProfile":
        object.__setattr__(self, "created_at", ensure_utc(self.created_at) or self.created_at)
        object.__setattr__(self, "activated_at", ensure_utc(self.activated_at))
        object.__setattr__(self, "deprecated_at", ensure_utc(self.deprecated_at))
        return self


class BusinessPolicySnapshot(PrimitiveModel):
    snapshot_id: str
    run_id: str
    profiles: list[BusinessPolicyProfile] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    manifest_ref: SourceRef | None = None

    @model_validator(mode="after")
    def _normalize_created_at(self) -> "BusinessPolicySnapshot":
        object.__setattr__(self, "created_at", ensure_utc(self.created_at) or self.created_at)
        return self

    @classmethod
    def create(cls, run_id: str, profiles: list[BusinessPolicyProfile]) -> "BusinessPolicySnapshot":
        return cls(
            snapshot_id=build_stable_id(
                "policy_snapshot",
                run_id,
                [(profile.profile_id, profile.version) for profile in profiles],
            ),
            run_id=run_id,
            profiles=profiles,
        )


class BusinessLearningSignal(PrimitiveModel):
    signal_id: str
    signal_type: str
    board_type: str | None = None
    target_layer: str | None = None
    description: str
    frequency: int = 1
    severity_score: float = 0.0
    related_feedback_ids: list[str] = Field(default_factory=list)
    related_object_refs: list[SourceRef] = Field(default_factory=list)
    suggested_policy_profile_id: str | None = None
    suggested_adjustment: dict[str, Any] = Field(default_factory=dict)
    status: str = "observed"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("frequency")
    @classmethod
    def _positive_frequency(cls, value: int) -> int:
        numeric = int(value)
        if numeric < 1:
            raise ValueError("learning signal frequency must be positive")
        return numeric

    @field_validator("severity_score")
    @classmethod
    def _unit_interval(cls, value: float) -> float:
        numeric = float(value)
        if not 0.0 <= numeric <= 1.0:
            raise ValueError("severity_score must be between 0 and 1")
        return round(numeric, 4)

    @model_validator(mode="after")
    def _normalize_datetimes(self) -> "BusinessLearningSignal":
        object.__setattr__(self, "created_at", ensure_utc(self.created_at) or self.created_at)
        object.__setattr__(self, "updated_at", ensure_utc(self.updated_at) or self.updated_at)
        return self


class BusinessPolicyCandidate(PrimitiveModel):
    candidate_id: str
    profile: BusinessPolicyProfile
    status: str = "candidate"
    based_on_learning_signal_ids: list[str] = Field(default_factory=list)
    regression_guard_ref: SourceRef | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _normalize_created_at(self) -> "BusinessPolicyCandidate":
        object.__setattr__(self, "created_at", ensure_utc(self.created_at) or self.created_at)
        return self


class BusinessRegressionGuardResult(PrimitiveModel):
    guard_id: str
    candidate_id: str | None = None
    status: str
    passed: bool
    checks: list[BusinessQualityCheck] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _normalize_evaluated_at(self) -> "BusinessRegressionGuardResult":
        object.__setattr__(self, "evaluated_at", ensure_utc(self.evaluated_at) or self.evaluated_at)
        if self.status == "pass" and not self.passed:
            raise ValueError("regression guard status=pass requires passed=True")
        if self.status == "block" and self.passed:
            raise ValueError("regression guard status=block requires passed=False")
        return self


def quality_snapshot_from_checks(
    checks: list[BusinessQualityCheck],
    *,
    score: float | None = None,
    confidence: float | None = None,
    warnings: list[str] | None = None,
    error_tags: list[str] | None = None,
) -> BusinessQualitySnapshot:
    return BusinessQualitySnapshot(
        score=score,
        confidence=confidence,
        checks=checks,
        warnings=warnings or [check.reason for check in checks if not check.passed and check.reason],
        error_tags=error_tags or [check.check_type for check in checks if not check.passed and check.severity in {"error", "block"}],
        requires_review=any(not check.passed and check.severity in {"warning", "error", "block"} for check in checks),
        review_reason=next((check.reason for check in checks if not check.passed and check.reason), None),
        evaluated_at=datetime.now(UTC),
    )
