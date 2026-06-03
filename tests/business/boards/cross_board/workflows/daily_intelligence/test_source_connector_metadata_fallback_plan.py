from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.source_connector_metadata_fallback_plan import (
    active_source_connector_metadata_fallback_phases,
    completed_source_connector_metadata_fallback_legacy_keys,
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
    assert phases[0].completed is True
    assert phases[1].legacy_keys == ("time",)
    assert phases[1].formal_fields == ("time_range",)
    assert phases[1].completed is False


def test_source_connector_metadata_fallback_plan_covers_active_legacy_keys() -> None:
    assert source_connector_metadata_fallback_legacy_keys() == (
        "time",
        "tag",
        "records",
    )


def test_source_connector_metadata_fallback_plan_tracks_completed_keys() -> None:
    assert completed_source_connector_metadata_fallback_legacy_keys() == ("mode",)
    assert [phase.phase_id for phase in active_source_connector_metadata_fallback_phases()] == [
        "phase-2-reddit-time",
        "phase-3-stackoverflow-tag",
        "phase-4-manual-records-shape",
    ]


def test_source_connector_metadata_fallback_phase_serializes_reviewable_payload() -> None:
    [phase, *_] = source_connector_metadata_fallback_deprecation_plan()

    assert phase.to_dict() == {
        "phase_id": "phase-1-github-mode",
        "source_type": "github",
        "legacy_keys": ["mode"],
        "formal_fields": ["github_mode"],
        "exit_criteria": list(phase.exit_criteria),
        "completed": True,
    }
    assert phase.exit_criteria
