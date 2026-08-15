from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from framework.events import (
    BusinessContext,
    EventCandidate,
    EventPage,
    GraphEventContext,
    GraphEventProjectionExporter,
    GraphRunIdentity,
    ProducerIdentity,
    StoredEvent,
    StreamSequenceCursor,
    checksum_for,
    default_event_schema_catalog,
    project_canonical_event,
    project_graph_event,
)
from framework.events.errors import EventContractError
from framework.events.projection import (
    CANONICAL_EVENT_PROJECTION_SCHEMA,
    GRAPH_EVENT_CONTEXT_EXTENSION,
    GRAPH_EVENT_PROJECTION_SCHEMA,
)


NOW = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
RUN_ID = "run-graph-projection"


class _Reader:
    def __init__(self, events: list[StoredEvent]) -> None:
        self.events = events
        self.requests = []

    def get_event(self, event_id: str, *, tenant_id: str | None = None):
        return next(
            (
                event
                for event in self.events
                if event.event_id == event_id and event.tenant_id == tenant_id
            ),
            None,
        )

    def get_stream_high_watermark(
        self,
        stream_id: str,
        *,
        tenant_id: str | None = None,
    ) -> int | None:
        return max(
            (
                event.stream_sequence
                for event in self.events
                if event.stream_id == stream_id and event.tenant_id == tenant_id
            ),
            default=None,
        )

    def read_stream(self, request):
        self.requests.append(request)
        high_watermark = request.through_sequence
        after_sequence = (
            request.cursor.after_sequence if request.cursor is not None else 0
        )
        matching = tuple(
            event
            for event in self.events
            if event.stream_id == request.stream_id
            and event.tenant_id == request.tenant_id
            and after_sequence < event.stream_sequence <= (high_watermark or 0)
        )[: request.limit]
        next_cursor = None
        if matching and matching[-1].stream_sequence < (high_watermark or 0):
            next_cursor = StreamSequenceCursor(
                stream_id=request.stream_id,
                tenant_id=request.tenant_id,
                after_sequence=matching[-1].stream_sequence,
                high_watermark=high_watermark,
            )
        return EventPage(
            stream_id=request.stream_id,
            tenant_id=request.tenant_id,
            events=matching,
            high_watermark=high_watermark,
            next_cursor=next_cursor,
        )


def test_graph_projection_is_bound_to_one_exact_graph_identity(tmp_path) -> None:
    events = [_graph_event(1), _graph_event(2, with_node=True)]
    exporter = GraphEventProjectionExporter(
        reader=_Reader(events),
        schema_catalog=default_event_schema_catalog(),
        page_size=1,
    )

    projection = exporter.export(
        stream_id=f"run:{RUN_ID}",
        target=tmp_path / "events.jsonl",
        tenant_id="tenant-a",
    )

    rows = [
        json.loads(line)
        for line in projection.path.read_text(encoding="utf-8").splitlines()
    ]
    assert projection.graph_identity == _graph_identity()
    assert projection.high_watermark == 2
    assert projection.event_count == 2
    assert [row["stream_sequence"] for row in rows] == [1, 2]
    assert all(
        row["projection_schema"] == GRAPH_EVENT_PROJECTION_SCHEMA for row in rows
    )
    assert all(row["graph_id"] == "research.paper-analysis" for row in rows)
    assert all("workflow_id" not in row for row in rows)
    assert all("step_id" not in row for row in rows)
    assert all("workflow_id" not in row["business_context"] for row in rows)
    assert rows[0]["node_id"] is None
    assert rows[1]["node_id"] == "analyze"
    assert rows[1]["node_instance_id"] == "analyze:1"


def test_graph_projection_verifies_bytes_against_durable_history(tmp_path) -> None:
    events = [_graph_event(1), _graph_event(2, with_node=True)]
    exporter = GraphEventProjectionExporter(
        reader=_Reader(events),
        schema_catalog=default_event_schema_catalog(),
    )
    projection = exporter.export(
        stream_id=f"run:{RUN_ID}",
        target=tmp_path / "events.jsonl",
        tenant_id="tenant-a",
    )

    verified = exporter.verify_existing(
        stream_id=projection.stream_id,
        target=projection.path,
        high_watermark=projection.high_watermark,
        event_count=projection.event_count,
        checksum=projection.checksum,
        tenant_id="tenant-a",
    )

    assert verified == projection
    projection.path.write_text('{"forged":true}\n', encoding="utf-8")
    with pytest.raises(EventContractError, match="does not match the durable event"):
        exporter.verify_existing(
            stream_id=projection.stream_id,
            target=projection.path,
            high_watermark=projection.high_watermark,
            event_count=projection.event_count,
            checksum=projection.checksum,
            tenant_id="tenant-a",
        )


def test_graph_projection_rejects_conflicting_identity_without_replacing_target(
    tmp_path,
) -> None:
    target = tmp_path / "events.jsonl"
    target.write_bytes(b"previous-complete-projection\n")
    events = [
        _graph_event(1),
        _graph_event(2, graph_checksum="sha256:" + "b" * 64),
    ]
    exporter = GraphEventProjectionExporter(
        reader=_Reader(events),
        schema_catalog=default_event_schema_catalog(),
        page_size=1,
    )

    with pytest.raises(EventContractError, match="conflicting Graph identity"):
        exporter.export(
            stream_id=f"run:{RUN_ID}",
            target=target,
            tenant_id="tenant-a",
        )

    assert target.read_bytes() == b"previous-complete-projection\n"
    assert list(tmp_path.glob(".events.jsonl.*.tmp")) == []


def test_graph_projection_rejects_missing_context_and_workflow_alias(tmp_path) -> None:
    missing_context = _graph_event(1, include_context=False)
    aliased = _graph_event(1, workflow_id="legacy-workflow")

    with pytest.raises(EventContractError, match="context extension is required"):
        project_graph_event(
            missing_context,
            schema_catalog=default_event_schema_catalog(),
        )
    with pytest.raises(EventContractError, match="legacy orchestration identity aliases"):
        project_graph_event(
            aliased,
            schema_catalog=default_event_schema_catalog(),
        )
    assert not (tmp_path / "events.jsonl").exists()


def test_graph_projection_redacts_secret_bearing_extensions() -> None:
    secret = "graph-projection-secret-DURABLE123456789"
    event = _graph_event(1, authorization=f"Bearer {secret}")

    row = project_graph_event(
        event,
        schema_catalog=default_event_schema_catalog(),
    )

    serialized = json.dumps(row, sort_keys=True)
    assert secret not in serialized
    assert row["extensions"]["authorization"] == "[REDACTED]"


def test_graph_projection_rejects_unknown_context_fields_and_moving_versions() -> None:
    context = _graph_context()
    context["unexpected"] = True
    with pytest.raises(EventContractError, match="fields are invalid"):
        GraphEventContext.from_dict(context)

    context = _graph_context()
    context["graph_version"] = "latest"
    with pytest.raises(EventContractError, match="must be an exact version"):
        GraphEventContext.from_dict(context)

    context = _graph_context()
    context["run_id"] = "../foreign-run"
    with pytest.raises(EventContractError, match="run_id is invalid"):
        GraphEventContext.from_dict(context)


def test_graph_projection_rejects_empty_uninitialized_stream(tmp_path) -> None:
    target = tmp_path / "events.jsonl"
    target.write_bytes(b"previous\n")
    exporter = GraphEventProjectionExporter(
        reader=_Reader([]),
        schema_catalog=default_event_schema_catalog(),
    )

    with pytest.raises(EventContractError, match="initialized Graph history"):
        exporter.export(
            stream_id=f"run:{RUN_ID}",
            target=target,
            tenant_id="tenant-a",
        )

    assert target.read_bytes() == b"previous\n"


def test_canonical_projection_is_domain_neutral_and_checksum_bound() -> None:
    event = _graph_event(1, workflow_id="historical-workflow", include_context=False)

    row = project_canonical_event(
        event,
        schema_catalog=default_event_schema_catalog(),
    )

    assert row["projection_schema"] == CANONICAL_EVENT_PROJECTION_SCHEMA
    assert "workflow_id" not in row
    assert row["business_context"]["workflow_id"] == "historical-workflow"
    projection_checksum = row.pop("projection_checksum")
    assert projection_checksum == checksum_for(row)
    assert row["source_content_checksum"] == event.content_checksum
    assert row["source_record_checksum"] == event.record_checksum


def _graph_identity(*, checksum: str = "sha256:" + "a" * 64) -> GraphRunIdentity:
    return GraphRunIdentity(
        run_id=RUN_ID,
        graph_id="research.paper-analysis",
        graph_version="1",
        graph_schema_version="newsroom.normalized-harness-graph/v3",
        compiler_version="3",
        normalized_graph_checksum=checksum,
    )


def _graph_context(*, checksum: str = "sha256:" + "a" * 64) -> dict:
    return GraphEventContext(identity=_graph_identity(checksum=checksum)).to_dict()


def _graph_event(
    sequence: int,
    *,
    with_node: bool = False,
    graph_checksum: str = "sha256:" + "a" * 64,
    include_context: bool = True,
    workflow_id: str | None = None,
    authorization: str | None = None,
) -> StoredEvent:
    context = GraphEventContext(
        identity=_graph_identity(checksum=graph_checksum),
        node_id="analyze" if with_node else None,
        node_instance_id="analyze:1" if with_node else None,
    )
    extensions: dict[str, object] = (
        {GRAPH_EVENT_CONTEXT_EXTENSION: context.to_dict()}
        if include_context
        else {}
    )
    if authorization is not None:
        extensions["authorization"] = authorization
    candidate = EventCandidate(
        event_id=f"evt-graph-{sequence}-{graph_checksum[-1]}",
        event_type=(
            "harness_graph_initialized"
            if sequence == 1
            else "harness_graph_decision_committed"
        ),
        data_schema="newsroom.harness-graph-control-commit/v1",
        source="io.newsroom.harness.control-plane",
        occurred_at=NOW + timedelta(seconds=sequence),
        stream_id=f"run:{RUN_ID}",
        correlation_id=RUN_ID,
        business_context=BusinessContext(
            run_id=RUN_ID,
            workflow_id=workflow_id,
        ),
        producer=ProducerIdentity(
            component="framework.harness.control_plane",
            version="1",
        ),
        tenant_id="tenant-a",
        payload={"commit": {"sequence": sequence}},
        extensions=extensions,
    )
    return StoredEvent(
        candidate=candidate,
        observed_at=NOW + timedelta(seconds=sequence, microseconds=1),
        stream_sequence=sequence,
    )
