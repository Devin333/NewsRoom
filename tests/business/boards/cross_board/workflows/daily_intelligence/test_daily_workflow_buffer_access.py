from __future__ import annotations

import pytest

from framework.workflow import DataBuffer
from business.boards.cross_board.workflows.daily_intelligence.workflow_buffer_access import (
    append_buffer_items,
    read_buffer_list,
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
