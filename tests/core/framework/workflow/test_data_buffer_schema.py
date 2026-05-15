import pytest

from core.framework.workflow import (
    BufferValueSchema,
    DataBufferSchemaError,
    ScopedDataBuffer,
    StepDataScope,
)


def test_registered_schema_allows_correct_type() -> None:
    buffer = ScopedDataBuffer()
    buffer.register_scope(StepDataScope(step_id="writer", write_keys={"report"}))
    buffer.register_schema(BufferValueSchema(key="report", value_type=dict))

    buffer.write(step_id="writer", key="report", value={"title": "Daily"})

    assert buffer.snapshot(redacted=False)["report"] == {"title": "Daily"}


def test_registered_schema_rejects_wrong_type() -> None:
    buffer = ScopedDataBuffer()
    buffer.register_scope(StepDataScope(step_id="writer", write_keys={"report"}))
    buffer.register_schema(BufferValueSchema(key="report", value_type=dict))

    with pytest.raises(DataBufferSchemaError):
        buffer.write(step_id="writer", key="report", value="not a dict")


def test_registered_schema_rejects_missing_required_fields() -> None:
    buffer = ScopedDataBuffer()
    buffer.register_scope(StepDataScope(step_id="writer", write_keys={"report"}))
    buffer.register_schema(
        BufferValueSchema(
            key="report",
            value_type=dict,
            required_fields={"title", "sections"},
        )
    )

    with pytest.raises(DataBufferSchemaError):
        buffer.write(step_id="writer", key="report", value={"title": "Daily"})


def test_registered_schema_rejects_schema_version_mismatch() -> None:
    buffer = ScopedDataBuffer()
    buffer.register_scope(StepDataScope(step_id="writer", write_keys={"report"}))
    buffer.register_schema(
        BufferValueSchema(
            key="report",
            value_type=dict,
            schema_version="v1",
        )
    )

    with pytest.raises(DataBufferSchemaError):
        buffer.write(
            step_id="writer",
            key="report",
            value={"title": "Daily"},
            schema_version="v2",
        )
