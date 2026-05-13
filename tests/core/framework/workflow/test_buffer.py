import pytest

from core.framework.workflow import DataBuffer, DataBufferPermissionError


def test_scoped_buffer_allows_declared_read_and_write() -> None:
    buffer = DataBuffer({"request": {"topic": "ai"}})
    scoped = buffer.scope(read_keys=["request"], write_keys=["plan"])

    assert scoped.read("request") == {"topic": "ai"}

    scoped.write("plan", {"steps": ["collect", "write"]})

    assert buffer.read("plan") == {"steps": ["collect", "write"]}
    assert scoped.list_allowed_reads() == ["request"]
    assert scoped.list_allowed_writes() == ["plan"]


def test_scoped_buffer_blocks_undeclared_read() -> None:
    buffer = DataBuffer({"request": {"topic": "ai"}})
    scoped = buffer.scope(read_keys=[], write_keys=[])

    with pytest.raises(DataBufferPermissionError, match="read key is not allowed"):
        scoped.read("request")


def test_scoped_buffer_blocks_undeclared_write() -> None:
    buffer = DataBuffer()
    scoped = buffer.scope(read_keys=[], write_keys=[])

    with pytest.raises(DataBufferPermissionError, match="write key is not allowed"):
        scoped.write("plan", {})


def test_buffer_snapshot_is_isolated_from_later_writes() -> None:
    buffer = DataBuffer({"items": ["a"]})
    snapshot = buffer.snapshot()

    buffer.write("items", ["b"])

    assert snapshot.to_dict() == {"items": ["a"]}
    assert buffer.snapshot().to_dict() == {"items": ["b"]}


def test_buffer_diff_reports_added_changed_and_removed_keys() -> None:
    original = DataBuffer(
        {
            "request": {"topic": "AI"},
            "removed": "old",
            "changed": {"version": 1},
        }
    ).snapshot()
    buffer = DataBuffer(
        {
            "request": {"topic": "AI"},
            "changed": {"version": 2},
        }
    )
    buffer.write("added", ["new"])

    diff = buffer.diff(original).to_dict()

    assert diff == {
        "added": {"added": ["new"]},
        "changed": {
            "changed": {
                "previous": {"version": 1},
                "current": {"version": 2},
            }
        },
        "removed": {"removed": "old"},
    }


def test_buffer_tracks_lineage_and_redacts_sensitive_keys() -> None:
    buffer = DataBuffer({"api_key": "secret", "request": {"topic": "ai"}})
    scoped = buffer.scope(read_keys=["request"], write_keys=["report"])

    scoped.write("report", "done", lineage={"step_id": "write_report", "source_key": "request"})

    assert buffer.lineage("report") == [{"step_id": "write_report", "source_key": "request"}]
    assert buffer.snapshot().lineage_to_dict()["report"][0]["step_id"] == "write_report"
    assert buffer.redact()["api_key"] == "[REDACTED]"
    assert buffer.redact()["report"] == "done"
