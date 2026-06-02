from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone as _tz
from hashlib import sha1
from typing import Any

UTC = _tz.utc

POLICY_EXPERIMENT_TARGET_TYPES = {
    "ranking_weight",
    "policy_threshold",
    "source_reliability",
    "skill_prompt_hint",
    "board_quality_gate",
}

LEGACY_OVERRIDE_TARGET_MAP = {
    "ranking_weight_override": "ranking_weight",
    "policy_threshold_override": "policy_threshold",
    "source_reliability_override": "source_reliability",
    "skill_prompt_hint_override": "skill_prompt_hint",
    "board_quality_gate_override": "board_quality_gate",
}

LEGACY_POLICY_EXPERIMENT_CHANGE_TYPES = frozenset(LEGACY_OVERRIDE_TARGET_MAP)


@dataclass(frozen=True)
class PolicyExperimentProfile:
    profile_id: str
    board_type: str
    target_type: str
    target_id: str
    parameters: dict[str, Any]
    rationale: str
    suggested_action: str
    measurement_metrics: list[str] = field(default_factory=lambda: [
        "quality_score",
        "card_count",
        "evidence_coverage",
        "duplicate_rate",
        "empty_output",
        "subscription_match",
    ])
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))

    def __post_init__(self) -> None:
        if self.target_type not in POLICY_EXPERIMENT_TARGET_TYPES:
            raise ValueError(f"unsupported policy experiment target_type: {self.target_type}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PolicyExperimentProfile":
        return cls(
            profile_id=str(payload["profile_id"]),
            board_type=str(payload["board_type"]),
            target_type=policy_experiment_target_type(str(payload["target_type"])),
            target_id=str(payload["target_id"]),
            parameters=dict(payload.get("parameters") or {}),
            rationale=str(payload.get("rationale") or ""),
            suggested_action=str(payload.get("suggested_action") or ""),
            measurement_metrics=list(payload.get("measurement_metrics") or []),
            created_at=str(payload.get("created_at") or datetime.now(UTC).isoformat().replace("+00:00", "Z")),
        )


@dataclass(frozen=True)
class AppliedPolicyExperiment:
    experiment_id: str
    proposal_id: str
    board_type: str
    profile_id: str
    target_type: str
    target_id: str
    parameters: dict[str, Any]
    applied_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    status: str = "active"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PolicyExperimentApplicationContext:
    run_id: str
    board_type: str
    applied_policy_experiments: list[dict[str, Any]] = field(default_factory=list)
    skipped_policy_experiments: list[dict[str, Any]] = field(default_factory=list)
    proposal_ids: list[str] = field(default_factory=list)
    measurement_plan: dict[str, Any] = field(default_factory=dict)

    @property
    def applied_overrides(self) -> list[dict[str, Any]]:
        return self.applied_policy_experiments

    @property
    def skipped_overrides(self) -> list[dict[str, Any]]:
        return self.skipped_policy_experiments

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["applied_overrides"] = list(self.applied_policy_experiments)
        payload["skipped_overrides"] = list(self.skipped_policy_experiments)
        return payload


def policy_experiment_target_type(value: str) -> str:
    normalized = LEGACY_OVERRIDE_TARGET_MAP.get(value, value)
    if normalized not in POLICY_EXPERIMENT_TARGET_TYPES:
        return "policy_threshold"
    return normalized


def policy_experiment_profile_id(*parts: Any) -> str:
    digest = sha1("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:12]
    return f"policy_exp_{digest}"


def is_legacy_policy_experiment_change_type(change_type: str) -> bool:
    return str(change_type) in LEGACY_POLICY_EXPERIMENT_CHANGE_TYPES


__all__ = [
    "AppliedPolicyExperiment",
    "LEGACY_OVERRIDE_TARGET_MAP",
    "LEGACY_POLICY_EXPERIMENT_CHANGE_TYPES",
    "POLICY_EXPERIMENT_TARGET_TYPES",
    "PolicyExperimentApplicationContext",
    "PolicyExperimentProfile",
    "is_legacy_policy_experiment_change_type",
    "policy_experiment_profile_id",
    "policy_experiment_target_type",
]
