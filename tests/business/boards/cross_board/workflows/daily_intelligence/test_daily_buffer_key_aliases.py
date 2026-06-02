from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.buffer_key_aliases import (
    with_namespaced_aliases,
    with_namespaced_read_keys,
    with_namespaced_write_keys,
)


def test_with_namespaced_aliases_adds_compatible_aliases_without_removing_legacy_keys() -> None:
    source_errors = []
    outputs = with_namespaced_aliases(
        {
            "source_errors": source_errors,
            "quality_events": [],
            "verification_result": {"status": "pass"},
            "unmapped": "kept",
        }
    )

    assert outputs["source_errors"] is source_errors
    assert outputs["sources.errors"] is source_errors
    assert outputs["quality.events"] == []
    assert outputs["quality.verification_result"] == {"status": "pass"}
    assert outputs["unmapped"] == "kept"


def test_with_namespaced_write_keys_declares_aliases_after_legacy_keys() -> None:
    keys = with_namespaced_write_keys(
        ["source_errors", "quality_events", "verification_result", "unmapped"]
    )

    assert keys == [
        "source_errors",
        "quality_events",
        "verification_result",
        "unmapped",
        "sources.errors",
        "quality.events",
        "quality.verification_result",
    ]


def test_with_namespaced_read_keys_declares_aliases_after_legacy_keys() -> None:
    keys = with_namespaced_read_keys(
        ["report_draft", "evidence_bundle", "quality_events", "unmapped"]
    )

    assert keys == [
        "report_draft",
        "evidence_bundle",
        "quality_events",
        "unmapped",
        "report.draft",
        "evidence.bundle",
        "quality.events",
    ]
