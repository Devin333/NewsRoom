from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.source_connector_metadata_fallback_plan import (
    source_connector_metadata_fallback_deprecation_plan,
    source_connector_metadata_fallback_legacy_keys,
)


def test_source_connector_metadata_fallback_plan_orders_specific_legacy_keys() -> None:
    phases = source_connector_metadata_fallback_deprecation_plan()

    assert [phase.phase_id for phase in phases] == [
        "phase-1-github-mode",
        "phase-2-reddit-time",
        "phase-3-stackoverflow-tag",
        "phase-4-manual-records-shape",
    ]
    assert phases[0].legacy_keys == ("mode",)
    assert phases[0].formal_fields == ("github_mode",)
    assert phases[1].legacy_keys == ("time",)
    assert phases[1].formal_fields == ("time_range",)


def test_source_connector_metadata_fallback_plan_covers_current_legacy_keys() -> None:
    assert source_connector_metadata_fallback_legacy_keys() == (
        "mode",
        "time",
        "tag",
        "records",
    )


def test_source_connector_metadata_fallback_phase_serializes_reviewable_payload() -> None:
    [phase, *_] = source_connector_metadata_fallback_deprecation_plan()

    assert phase.to_dict() == {
        "phase_id": "phase-1-github-mode",
        "source_type": "github",
        "legacy_keys": ["mode"],
        "formal_fields": ["github_mode"],
        "exit_criteria": list(phase.exit_criteria),
    }
    assert phase.exit_criteria
