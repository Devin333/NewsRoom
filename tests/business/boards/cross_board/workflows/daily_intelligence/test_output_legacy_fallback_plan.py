from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.buffer_key_aliases import (
    legacy_key_for,
)
from business.boards.cross_board.workflows.daily_intelligence.output_legacy_fallback_plan import (
    artifact_legacy_fallback_deprecation_plan,
    artifact_legacy_fallback_legacy_keys,
)
from business.boards.cross_board.workflows.daily_intelligence.output_projection import (
    DAILY_AGENTIC_ARTIFACT_OUTPUT_KEYS,
    DAILY_EVIDENCE_ARTIFACT_OUTPUT_KEYS,
    DAILY_QUALITY_ARTIFACT_OUTPUT_KEYS,
    DAILY_REPORT_ARTIFACT_OUTPUT_KEYS,
    DAILY_SOURCE_DIAGNOSTIC_ARTIFACT_OUTPUT_KEYS,
    DAILY_SOURCE_RECOLLECTION_ARTIFACT_OUTPUT_KEYS,
)


def test_artifact_legacy_fallback_deprecation_plan_orders_low_risk_phases_first() -> None:
    phases = artifact_legacy_fallback_deprecation_plan()

    assert [phase.phase_id for phase in phases] == [
        "phase-1-report-quality",
        "phase-2-evidence",
        "phase-3-source-diagnostics",
        "phase-4-agentic",
        "phase-5-source-recollection",
    ]
    assert phases[0].artifact_projection == "report_and_quality_artifacts"
    assert "final_report" in phases[0].legacy_keys
    assert "quality_result" in phases[0].legacy_keys
    assert "agent_feedback_summary" in phases[3].legacy_keys


def test_artifact_legacy_fallback_plan_covers_all_aliasable_artifact_keys() -> None:
    expected_legacy_keys = _aliasable_legacy_keys(
        (
            *DAILY_REPORT_ARTIFACT_OUTPUT_KEYS,
            *DAILY_QUALITY_ARTIFACT_OUTPUT_KEYS,
            *DAILY_EVIDENCE_ARTIFACT_OUTPUT_KEYS,
            *DAILY_SOURCE_DIAGNOSTIC_ARTIFACT_OUTPUT_KEYS,
            *DAILY_AGENTIC_ARTIFACT_OUTPUT_KEYS,
            *DAILY_SOURCE_RECOLLECTION_ARTIFACT_OUTPUT_KEYS,
        )
    )

    assert artifact_legacy_fallback_legacy_keys() == expected_legacy_keys


def test_artifact_legacy_fallback_phase_serializes_reviewable_payload() -> None:
    [phase, *_] = artifact_legacy_fallback_deprecation_plan()

    assert phase.to_dict() == {
        "phase_id": "phase-1-report-quality",
        "artifact_projection": "report_and_quality_artifacts",
        "legacy_keys": list(phase.legacy_keys),
        "namespaced_keys": list(phase.namespaced_keys),
        "exit_criteria": list(phase.exit_criteria),
    }
    assert len(phase.legacy_keys) == len(phase.namespaced_keys)
    assert phase.exit_criteria


def _aliasable_legacy_keys(keys: tuple[str, ...]) -> tuple[str, ...]:
    values: list[str] = []
    for key in keys:
        legacy_key = legacy_key_for(key)
        if legacy_key is not None and legacy_key not in values:
            values.append(legacy_key)
    return tuple(values)
