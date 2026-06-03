from __future__ import annotations

from dataclasses import dataclass

from business.boards.cross_board.workflows.daily_intelligence.buffer_key_aliases import (
    legacy_key_for,
    namespaced_key_for,
)
from business.boards.cross_board.workflows.daily_intelligence.output_projection import (
    DAILY_AGENTIC_ARTIFACT_OUTPUT_KEYS,
    DAILY_EVIDENCE_ARTIFACT_OUTPUT_KEYS,
    DAILY_QUALITY_ARTIFACT_OUTPUT_KEYS,
    DAILY_REPORT_ARTIFACT_OUTPUT_KEYS,
    DAILY_SOURCE_DIAGNOSTIC_ARTIFACT_OUTPUT_KEYS,
    DAILY_SOURCE_RECOLLECTION_ARTIFACT_OUTPUT_KEYS,
)


@dataclass(frozen=True)
class LegacyFallbackPhase:
    phase_id: str
    artifact_projection: str
    legacy_keys: tuple[str, ...]
    namespaced_keys: tuple[str, ...]
    exit_criteria: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "phase_id": self.phase_id,
            "artifact_projection": self.artifact_projection,
            "legacy_keys": list(self.legacy_keys),
            "namespaced_keys": list(self.namespaced_keys),
            "exit_criteria": list(self.exit_criteria),
        }


def artifact_legacy_fallback_deprecation_plan() -> tuple[LegacyFallbackPhase, ...]:
    return (
        _phase(
            phase_id="phase-1-report-quality",
            artifact_projection="report_and_quality_artifacts",
            keys=(*DAILY_REPORT_ARTIFACT_OUTPUT_KEYS, *DAILY_QUALITY_ARTIFACT_OUTPUT_KEYS),
            exit_criteria=(
                "Report/finalization writers emit report.* and quality.* keys in all runtime profiles.",
                "Artifact publisher tests cover namespaced-only report and quality payloads.",
            ),
        ),
        _phase(
            phase_id="phase-2-evidence",
            artifact_projection="evidence_artifacts",
            keys=DAILY_EVIDENCE_ARTIFACT_OUTPUT_KEYS,
            exit_criteria=(
                "Evidence builder emits evidence.* keys before artifact publication.",
                "Evidence artifact tests no longer need legacy-only evidence payloads.",
            ),
        ),
        _phase(
            phase_id="phase-3-source-diagnostics",
            artifact_projection="source_diagnostic_artifacts",
            keys=DAILY_SOURCE_DIAGNOSTIC_ARTIFACT_OUTPUT_KEYS,
            exit_criteria=(
                "Source collection and recollection emit sources.* diagnostics for live and offline profiles.",
                "Source diagnostic artifacts read no legacy-only source diagnostic payloads.",
            ),
        ),
        _phase(
            phase_id="phase-4-agentic",
            artifact_projection="agentic_artifacts",
            keys=DAILY_AGENTIC_ARTIFACT_OUTPUT_KEYS,
            exit_criteria=(
                "Agent loop specs emit agent.<label>.loop.* telemetry for all agentic steps.",
                "Agentic artifact tests no longer need legacy-only agent loop telemetry payloads.",
            ),
        ),
        _phase(
            phase_id="phase-5-source-recollection",
            artifact_projection="source_recollection_artifacts",
            keys=DAILY_SOURCE_RECOLLECTION_ARTIFACT_OUTPUT_KEYS,
            exit_criteria=(
                "Source recollection profile, plan, report, and assessment are consumed through sources.* keys.",
                "Source recollection artifact tests no longer need legacy-only recollection payloads.",
            ),
        ),
    )


def artifact_legacy_fallback_legacy_keys() -> tuple[str, ...]:
    keys: list[str] = []
    for phase in artifact_legacy_fallback_deprecation_plan():
        for legacy_key in phase.legacy_keys:
            if legacy_key not in keys:
                keys.append(legacy_key)
    return tuple(keys)


def _phase(
    *,
    phase_id: str,
    artifact_projection: str,
    keys: tuple[str, ...],
    exit_criteria: tuple[str, ...],
) -> LegacyFallbackPhase:
    legacy_keys: list[str] = []
    namespaced_keys: list[str] = []
    for key in keys:
        legacy_key = legacy_key_for(key)
        namespaced_key = namespaced_key_for(legacy_key or key)
        if legacy_key is None or namespaced_key is None:
            continue
        if legacy_key not in legacy_keys:
            legacy_keys.append(legacy_key)
            namespaced_keys.append(namespaced_key)
    return LegacyFallbackPhase(
        phase_id=phase_id,
        artifact_projection=artifact_projection,
        legacy_keys=tuple(legacy_keys),
        namespaced_keys=tuple(namespaced_keys),
        exit_criteria=exit_criteria,
    )


__all__ = [
    "LegacyFallbackPhase",
    "artifact_legacy_fallback_deprecation_plan",
    "artifact_legacy_fallback_legacy_keys",
]
