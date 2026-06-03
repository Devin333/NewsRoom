from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.output_projection import (
    daily_output_contains,
    daily_output_value,
)


@dataclass(frozen=True)
class DailyEvidenceArtifact:
    artifact_key: str
    relative_path: str
    payload: Any


def project_daily_evidence_artifacts(
    output: Mapping[str, Any],
) -> list[DailyEvidenceArtifact]:
    artifacts: list[DailyEvidenceArtifact] = []

    if daily_output_contains(output, "evidence_bundle"):
        evidence_bundle = daily_output_value(output, "evidence_bundle")
        artifacts.append(
            DailyEvidenceArtifact(
                artifact_key="evidence_bundle",
                relative_path="evidence_bundle.json",
                payload=evidence_bundle,
            )
        )

        source_map = daily_output_value(output, "evidence_source_map")
        if source_map is None:
            source_map = evidence_source_map_from_bundle(evidence_bundle)
        if source_map is not None:
            artifacts.append(
                DailyEvidenceArtifact(
                    artifact_key="evidence_source_map",
                    relative_path="evidence_source_map.json",
                    payload=source_map,
                )
            )
    elif daily_output_contains(output, "evidence_source_map"):
        artifacts.append(
            DailyEvidenceArtifact(
                artifact_key="evidence_source_map",
                relative_path="evidence_source_map.json",
                payload=daily_output_value(output, "evidence_source_map"),
            )
        )

    for artifact_key, relative_path in {
        "evidence_scores": "evidence_scores.json",
        "candidate_claims": "candidate_claims.json",
        "verified_findings": "verified_findings.json",
    }.items():
        if daily_output_contains(output, artifact_key):
            artifacts.append(
                DailyEvidenceArtifact(
                    artifact_key=artifact_key,
                    relative_path=relative_path,
                    payload=daily_output_value(output, artifact_key),
                )
            )

    return artifacts


def evidence_source_map_from_bundle(evidence_bundle: Any) -> dict[str, list[str]] | None:
    source_map = _field_value(evidence_bundle, "source_map")
    if source_map is None:
        return None
    return {str(key): list(value) for key, value in source_map.items()}


def _field_value(value: Any, field_name: str) -> Any:
    if hasattr(value, field_name):
        return getattr(value, field_name)
    if isinstance(value, Mapping):
        return value.get(field_name)
    return None


__all__ = [
    "DailyEvidenceArtifact",
    "evidence_source_map_from_bundle",
    "project_daily_evidence_artifacts",
]
