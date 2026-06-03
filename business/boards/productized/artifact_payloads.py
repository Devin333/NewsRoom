from __future__ import annotations

from collections.abc import Mapping
from typing import Any


BOARD_ARTIFACTS: dict[str, str] = {
    "board_output": "board_output.json",
    "cards": "cards.json",
    "detail_pages": "detail_pages.json",
    "insights": "insights.json",
    "quality_summary": "quality_summary.json",
    "subscription_payload": "subscription_payload.json",
    "feedback_events": "feedback_events.json",
    "learning_signals": "learning_signals.json",
    "improvement_recommendations": "improvement_recommendations.json",
    "improvement_proposals": "improvement_proposals.json",
    "policy_experiment_application_context": "policy_experiment_application_context.json",
    "applied_policy_experiments": "applied_policy_experiments.json",
    "skipped_policy_experiments": "skipped_policy_experiments.json",
    "applied_overrides": "applied_overrides.json",
    "improvement_measurement": "improvement_measurement.json",
}


class MissingProductizedArtifactPayload:
    pass


MISSING_PRODUCTIZED_ARTIFACT_PAYLOAD = MissingProductizedArtifactPayload()


def productized_artifact_payload(
    output: Mapping[str, Any],
    artifact_key: str,
) -> Any | MissingProductizedArtifactPayload:
    if artifact_key in output:
        return output[artifact_key]
    if artifact_key == "applied_overrides":
        return output.get("applied_policy_experiments", MISSING_PRODUCTIZED_ARTIFACT_PAYLOAD)
    return MISSING_PRODUCTIZED_ARTIFACT_PAYLOAD


__all__ = [
    "BOARD_ARTIFACTS",
    "MISSING_PRODUCTIZED_ARTIFACT_PAYLOAD",
    "MissingProductizedArtifactPayload",
    "productized_artifact_payload",
]
