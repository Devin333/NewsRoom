import pytest

from core.framework.workflow import (
    DataBufferKeyError,
    DataBufferReadPermissionError,
    DataBufferWritePermissionError,
    ScopedDataBuffer,
    StepDataScope,
)


def test_step_can_read_declared_read_key() -> None:
    buffer = ScopedDataBuffer()
    buffer.seed_request_key("input", "hello")
    buffer.register_scope(
        StepDataScope(
            step_id="writer",
            read_keys={"input"},
            write_keys={"output"},
        )
    )

    assert buffer.read(step_id="writer", key="input") == "hello"


def test_step_can_read_optional_read_key() -> None:
    buffer = ScopedDataBuffer()
    buffer.seed_request_key("previous_report", "old")
    buffer.register_scope(
        StepDataScope(
            step_id="writer",
            optional_read_keys={"previous_report"},
            write_keys={"output"},
        )
    )

    assert buffer.read(step_id="writer", key="previous_report") == "old"


def test_step_cannot_read_undeclared_key() -> None:
    buffer = ScopedDataBuffer()
    buffer.seed_request_key("input", "hello")
    buffer.register_scope(
        StepDataScope(
            step_id="writer",
            read_keys=set(),
            write_keys={"output"},
        )
    )

    with pytest.raises(DataBufferReadPermissionError):
        buffer.read(step_id="writer", key="input")


def test_missing_required_key_raises_buffer_key_error() -> None:
    buffer = ScopedDataBuffer()
    buffer.register_scope(
        StepDataScope(
            step_id="writer",
            read_keys={"input"},
            write_keys={"output"},
        )
    )

    with pytest.raises(DataBufferKeyError):
        buffer.read(step_id="writer", key="input")


def test_optional_missing_key_returns_default() -> None:
    buffer = ScopedDataBuffer()
    buffer.register_scope(
        StepDataScope(
            step_id="writer",
            optional_read_keys={"previous_report"},
            write_keys={"output"},
        )
    )

    assert buffer.read(
        step_id="writer",
        key="previous_report",
        required=False,
        default=None,
    ) is None


def test_step_can_write_declared_write_key() -> None:
    buffer = ScopedDataBuffer()
    buffer.register_scope(
        StepDataScope(
            step_id="writer",
            read_keys=set(),
            write_keys={"output"},
        )
    )

    buffer.write(step_id="writer", key="output", value={"ok": True})

    assert buffer.snapshot(redacted=False).to_dict()["output"] == {"ok": True}


def test_step_cannot_write_undeclared_key() -> None:
    buffer = ScopedDataBuffer()
    buffer.register_scope(
        StepDataScope(
            step_id="writer",
            read_keys=set(),
            write_keys={"output"},
        )
    )

    with pytest.raises(DataBufferWritePermissionError):
        buffer.write(step_id="writer", key="other", value={})


def test_scoped_view_automatically_supplies_step_id() -> None:
    buffer = ScopedDataBuffer()
    buffer.seed_request_key("input", "hello")
    buffer.register_scope(
        StepDataScope(
            step_id="writer",
            read_keys={"input"},
            write_keys={"output"},
        )
    )

    scoped = buffer.scoped("writer")

    assert scoped.read("input") == "hello"
    scoped.write("output", "done")
    assert buffer.read(step_id="writer", key="input") == "hello"
    assert buffer.snapshot(redacted=False).to_dict()["output"] == "done"
