from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from business.foundation.value_normalization import list_value, to_plain_dict


@dataclass(frozen=True)
class SourceRecollectionFinalizationPolicyDecision:
    recommended_action: str | None = None
    assessment: dict[str, Any] | None = None

    @property
    def should_apply(self) -> bool:
        return self.recommended_action is not None and self.assessment is not None


def select_source_recollection_finalization_policy(
    assessment: Any,
    *,
    strict_gate_required: bool,
) -> SourceRecollectionFinalizationPolicyDecision:
    if not strict_gate_required:
        return SourceRecollectionFinalizationPolicyDecision()
    payload = to_plain_dict(assessment)
    if not payload:
        return SourceRecollectionFinalizationPolicyDecision()
    if _requires_review(payload):
        return SourceRecollectionFinalizationPolicyDecision(
            recommended_action="human_review",
            assessment=payload,
        )
    return SourceRecollectionFinalizationPolicyDecision()


def source_recollection_quality_metadata(assessment: Any) -> dict[str, Any]:
    payload = to_plain_dict(assessment)
    if not payload:
        return {}
    return {
        "source_recollection_quality": {
            "plan_id": payload.get("plan_id"),
            "profile_id": payload.get("profile_id"),
            "decision": payload.get("decision"),
            "severity": payload.get("severity"),
            "route": payload.get("route"),
            "recommended_action": payload.get("recommended_action"),
            "failed_thresholds": list_value(payload.get("failed_thresholds")),
            "issues": list_value(payload.get("issues")),
        }
    }


def _requires_review(assessment: Mapping[str, Any]) -> bool:
    decision = _text(assessment.get("decision"))
    route = _text(assessment.get("route"))
    recommended_action = _text(assessment.get("recommended_action"))
    failed_thresholds = list_value(assessment.get("failed_thresholds"))
    return (
        decision == "insufficient"
        or route == "source_recollection_quality_review"
        or recommended_action == "review_source_recollection"
        or bool(failed_thresholds)
    )


def _text(value: Any) -> str:
    return str(value or "").strip().lower()


__all__ = [
    "SourceRecollectionFinalizationPolicyDecision",
    "select_source_recollection_finalization_policy",
    "source_recollection_quality_metadata",
]
