from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from framework.events import (
    BusinessContext,
    EventCandidate,
    EventPage,
    PayloadReference,
    ProducerIdentity,
    StoredEvent,
    StreamSequenceCursor,
    checksum_for,
    default_event_schema_catalog,
)
from framework.events.errors import EventContractError
from framework.workflow.runtime.event_projection import (
    WorkflowEventProjectionExporter,
)


NOW = datetime(2026, 7, 15, 9, 0, tzinfo=UTC)


class _Reader:
    def __init__(self, events: list[StoredEvent]) -> None:
        self.events = events
        self.requests = []

    def get_stream_high_watermark(self, stream_id: str, *, tenant_id=None):
        matching = [
            event
            for event in self.events
            if event.stream_id == stream_id and event.tenant_id == tenant_id
        ]
        return matching[-1].stream_sequence if matching else None

    def read_stream(self, request):
        self.requests.append(request)
        high_watermark = request.through_sequence or self.get_stream_high_watermark(
            request.stream_id,
            tenant_id=request.tenant_id,
        )
        after_sequence = request.cursor.after_sequence if request.cursor is not None else 0
        matching = [
            event
            for event in self.events
            if event.stream_id == request.stream_id
            and event.tenant_id == request.tenant_id
            and after_sequence < event.stream_sequence <= high_watermark
        ]
        page_events = tuple(matching[: request.limit])
        next_cursor = None
        if page_events and page_events[-1].stream_sequence < high_watermark:
            next_cursor = StreamSequenceCursor(
                stream_id=request.stream_id,
                tenant_id=request.tenant_id,
                after_sequence=page_events[-1].stream_sequence,
                high_watermark=high_watermark,
            )
        return EventPage(
            stream_id=request.stream_id,
            tenant_id=request.tenant_id,
            events=page_events,
            high_watermark=high_watermark,
            next_cursor=next_cursor,
        )


def test_projection_is_ordered_deterministic_and_bound_to_fixed_watermark(tmp_path) -> None:
    events = [_stored_event(index) for index in range(1, 4)]
    reader = _Reader(events)
    exporter = WorkflowEventProjectionExporter(
        reader=reader,
        schema_catalog=default_event_schema_catalog(),
        page_size=2,
    )

    first = exporter.export(
        stream_id="run:run-projection",
        target=tmp_path / "first.jsonl",
    )
    second = exporter.export(
        stream_id="run:run-projection",
        target=tmp_path / "second.jsonl",
        through_sequence=3,
    )

    first_bytes = first.path.read_bytes()
    assert first_bytes == second.path.read_bytes()
    assert first.high_watermark == 3
    assert first.event_count == 3
    assert first.checksum == f"sha256:{sha256(first_bytes).hexdigest()}"
    assert {request.through_sequence for request in reader.requests} == {3}

    rows = [json.loads(line) for line in first_bytes.decode("utf-8").splitlines()]
    assert [row["stream_sequence"] for row in rows] == [1, 2, 3]
    assert [row["event_id"] for row in rows] == ["evt-1", "evt-2", "evt-3"]
    assert all(row["run_id"] == "run-projection" for row in rows)
    assert all(row["workflow_id"] == "wf-projection" for row in rows)
    assert rows[1]["step_id"] == "step-2"
    assert rows[1]["component"] == "framework.workflow.runtime"


def test_empty_projection_has_explicit_empty_checksum(tmp_path) -> None:
    exporter = WorkflowEventProjectionExporter(
        reader=_Reader([]),
        schema_catalog=default_event_schema_catalog(),
    )

    projection = exporter.export(
        stream_id="run:run-empty",
        target=tmp_path / "events.jsonl",
    )

    assert projection.path.read_bytes() == b""
    assert projection.high_watermark is None
    assert projection.event_count == 0
    assert projection.checksum == f"sha256:{sha256(b'').hexdigest()}"


def test_existing_projection_verifies_against_the_recorded_durable_prefix(
    tmp_path,
) -> None:
    reader = _Reader([_stored_event(index) for index in range(1, 4)])
    exporter = WorkflowEventProjectionExporter(
        reader=reader,
        schema_catalog=default_event_schema_catalog(),
        page_size=2,
    )
    projection = exporter.export(
        stream_id="run:run-projection",
        target=tmp_path / "events.jsonl",
    )
    reader.events.append(_stored_event(4))

    verified = exporter.verify_existing(
        stream_id=projection.stream_id,
        target=projection.path,
        high_watermark=projection.high_watermark,
        event_count=projection.event_count,
        checksum=projection.checksum,
    )

    assert verified == projection


def test_existing_projection_rejects_rows_not_backed_by_durable_history(
    tmp_path,
) -> None:
    exporter = WorkflowEventProjectionExporter(
        reader=_Reader([_stored_event(1)]),
        schema_catalog=default_event_schema_catalog(),
    )
    projection = exporter.export(
        stream_id="run:run-projection",
        target=tmp_path / "events.jsonl",
    )
    row = json.loads(projection.path.read_text(encoding="utf-8"))
    row["event_id"] = "forged-event"
    projection.path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(EventContractError, match="does not match the durable event"):
        exporter.verify_existing(
            stream_id=projection.stream_id,
            target=projection.path,
            high_watermark=projection.high_watermark,
            event_count=projection.event_count,
            checksum=projection.checksum,
        )


def test_projection_excludes_events_appended_after_captured_watermark(tmp_path) -> None:
    class AppendingReader(_Reader):
        def read_stream(self, request):
            page = super().read_stream(request)
            if len(self.requests) == 1:
                self.events.append(_stored_event(4))
            return page

    exporter = WorkflowEventProjectionExporter(
        reader=AppendingReader([_stored_event(index) for index in range(1, 4)]),
        schema_catalog=default_event_schema_catalog(),
        page_size=2,
    )

    projection = exporter.export(
        stream_id="run:run-projection",
        target=tmp_path / "events.jsonl",
    )

    rows = [json.loads(line) for line in projection.path.read_text().splitlines()]
    assert projection.high_watermark == 3
    assert [row["stream_sequence"] for row in rows] == [1, 2, 3]


def test_projection_redacts_again_and_uses_explicit_source_checksums(tmp_path) -> None:
    secret = "resume-secret-value"
    event = _custom_event(
        event_type="workflow_resumed",
        payload={
            "workflow_version": "1",
            "profile": "test",
            "checkpoint_id": "checkpoint-1",
            "resume_metadata": {"token": secret},
        },
    )
    exporter = WorkflowEventProjectionExporter(
        reader=_Reader([event]),
        schema_catalog=default_event_schema_catalog(),
    )

    projection = exporter.export(
        stream_id=event.stream_id,
        target=tmp_path / "events.jsonl",
    )

    serialized = projection.path.read_text(encoding="utf-8")
    row = json.loads(serialized)
    assert secret not in serialized
    assert row["source_content_checksum"] == event.content_checksum
    assert row["source_record_checksum"] == event.record_checksum
    projected_checksum = row.pop("projection_checksum")
    assert projected_checksum == checksum_for(row)
    assert "content_checksum" not in row
    assert "record_checksum" not in row


def test_projection_redacts_secret_bearing_extensions(tmp_path) -> None:
    secret = "metadata-DURABLEEVENTSENTINEL123456789"
    event = _custom_event(
        event_type="workflow_started",
        payload={"workflow_version": "1", "profile": "test"},
        extensions={
            "authorization": f"Bearer {secret}",
            "diagnostic": f"request failed with {secret}",
        },
    )
    projection = WorkflowEventProjectionExporter(
        reader=_Reader([event]),
        schema_catalog=default_event_schema_catalog(),
    ).export(
        stream_id=event.stream_id,
        target=tmp_path / "events.jsonl",
    )

    serialized = projection.path.read_text(encoding="utf-8")
    row = json.loads(serialized)
    assert secret not in serialized
    assert row["extensions"]["authorization"] == "[REDACTED]"
    assert row["extensions"]["diagnostic"] == "request failed with [REDACTED]"


def test_projection_preserves_payload_reference_exclusivity(tmp_path) -> None:
    event = _custom_event(
        event_type="workflow_started",
        payload=None,
        payload_ref=PayloadReference(
            uri="artifact://run-projection/oversized.json",
            expected_checksum="sha256:" + "a" * 64,
            size_bytes=100_000,
        ),
    )
    exporter = WorkflowEventProjectionExporter(
        reader=_Reader([event]),
        schema_catalog=default_event_schema_catalog(),
    )

    projection = exporter.export(
        stream_id=event.stream_id,
        target=tmp_path / "events.jsonl",
    )

    row = json.loads(projection.path.read_text(encoding="utf-8"))
    assert row["payload"] is None
    assert row["payload_ref"]["uri"] == "artifact://run-projection/oversized.json"


def test_projection_failure_preserves_previous_target_and_removes_temp_file(
    tmp_path,
) -> None:
    class FailingReader(_Reader):
        def read_stream(self, request):
            if self.requests:
                raise RuntimeError("reader failed mid-projection")
            return super().read_stream(request)

    target = tmp_path / "events.jsonl"
    target.write_bytes(b"previous\n")
    exporter = WorkflowEventProjectionExporter(
        reader=FailingReader([_stored_event(index) for index in range(1, 4)]),
        schema_catalog=default_event_schema_catalog(),
        page_size=2,
    )

    with pytest.raises(RuntimeError, match="mid-projection"):
        exporter.export(stream_id="run:run-projection", target=target)

    assert target.read_bytes() == b"previous\n"
    assert list(tmp_path.glob(".events.jsonl.*.tmp")) == []


def _stored_event(index: int) -> StoredEvent:
    step_id = None if index == 1 else f"step-{index}"
    candidate = EventCandidate(
        event_id=f"evt-{index}",
        event_type="workflow_started" if index == 1 else "step_started",
        data_schema="newsroom.workflow-event/v1",
        source="io.newsroom.workflow.runtime",
        occurred_at=NOW + timedelta(seconds=index),
        stream_id="run:run-projection",
        correlation_id="run-projection",
        business_context=BusinessContext(
            run_id="run-projection",
            workflow_id="wf-projection",
            step_id=step_id,
        ),
        producer=ProducerIdentity(component="framework.workflow.runtime", version="1"),
        payload=(
            {
                "workflow_id": "wf-projection",
                "workflow_version": "1",
                "profile": "test",
            }
            if index == 1
            else {
                "step_id": step_id,
                "step_type": "function",
                "attempt": 1,
                "max_attempts": 1,
            }
        ),
    )
    return StoredEvent(
        candidate=candidate,
        observed_at=NOW + timedelta(seconds=index, microseconds=1),
        stream_sequence=index,
    )


def _custom_event(
    *,
    event_type: str,
    payload,
    payload_ref: PayloadReference | None = None,
    extensions=None,
) -> StoredEvent:
    candidate = EventCandidate(
        event_id=f"evt-{event_type}",
        event_type=event_type,
        data_schema="newsroom.workflow-event/v1",
        source="io.newsroom.workflow.runtime",
        occurred_at=NOW,
        stream_id="run:run-projection",
        correlation_id="run-projection",
        business_context=BusinessContext(
            run_id="run-projection",
            workflow_id="wf-projection",
        ),
        producer=ProducerIdentity(component="framework.workflow.runtime", version="1"),
        payload=payload,
        payload_ref=payload_ref,
        extensions=extensions or {},
    )
    return StoredEvent(candidate=candidate, observed_at=NOW, stream_sequence=1)
