from __future__ import annotations

import pytest

from framework.workflow import DataBuffer
from business.boards.cross_board.workflows.daily_intelligence.workflow_buffer_access import (
    append_buffer_items,
    read_buffer_list,
    read_buffer_value,
    read_optional_buffer_value,
)


def test_read_buffer_list_returns_copy_without_mutating_buffer_value() -> None:
    buffer = DataBuffer({"events": ["existing"]}).scope(read_keys=["events"], write_keys=[])

    events = read_buffer_list(buffer, "events")
    events.append("new")

    assert events == ["existing", "new"]
    assert buffer.read("events") == ["existing"]


def test_append_buffer_items_returns_copy_with_new_items() -> None:
    buffer = DataBuffer({"events": ["existing"]}).scope(read_keys=["events"], write_keys=[])

    events = append_buffer_items(buffer, "events", "new", "another")

    assert events == ["existing", "new", "another"]
    assert buffer.read("events") == ["existing"]


def test_read_buffer_list_rejects_non_collection_value() -> None:
    buffer = DataBuffer({"events": "not-a-list"}).scope(read_keys=["events"], write_keys=[])

    with pytest.raises(TypeError, match="must contain a list or tuple"):
        read_buffer_list(buffer, "events")


def test_read_buffer_value_prefers_namespaced_alias() -> None:
    buffer = DataBuffer(
        {
            "report_draft": {"version": "legacy"},
            "report.draft": {"version": "namespaced"},
        }
    ).scope(read_keys=["report_draft", "report.draft"], write_keys=[])

    assert read_buffer_value(buffer, "report_draft") == {"version": "namespaced"}


def test_read_buffer_value_falls_back_to_legacy_when_alias_is_not_scoped() -> None:
    buffer = DataBuffer({"report_draft": {"version": "legacy"}}).scope(
        read_keys=["report_draft"],
        write_keys=[],
    )

    assert read_buffer_value(buffer, "report_draft") == {"version": "legacy"}


def test_read_buffer_value_reads_namespaced_key_when_legacy_is_not_scoped() -> None:
    buffer = DataBuffer({"quality.events": ["namespaced"]}).scope(
        read_keys=["quality.events"],
        write_keys=[],
    )

    assert read_buffer_list(buffer, "quality_events") == ["namespaced"]


def test_read_optional_buffer_value_returns_default_when_no_candidate_is_scoped() -> None:
    buffer = DataBuffer({}).scope(read_keys=[], write_keys=[])

    assert read_optional_buffer_value(buffer, "report_draft", default={"missing": True}) == {
        "missing": True
    }
