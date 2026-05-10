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
