from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from framework.events import (
    BusinessContext,
    EventSchemaCatalog,
    EventSchemaRegistration,
    EventRuntime,
    TraceContext,
    thaw_canonical_json,
)
from framework.events.errors import EventContextConflictError, EventStoreUnavailableError
from framework.workflow.runtime.event_emitter import (
    ScopedDurableWorkflowEventEmitter,
    WorkflowEventRecorderFacade,
)
from infrastructure.storage.events.sqlite import SQLiteEventStore


NOW = datetime(2026, 7, 16, 10, 0, tzinfo=UTC)


def _emitter(tmp_path: Path) -> ScopedDurableWorkflowEventEmitter:
    catalog = _catalog()
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    return ScopedDurableWorkflowEventEmitter(
        runtime=EventRuntime(store=store, schema_catalog=catalog),
        reader=store,
        schema_catalog=catalog,
        stream_id="run:run-scoped",
        base_business_context=BusinessContext(
            run_id="run-scoped",
            workflow_id="workflow-scoped",
        ),
    )


def _catalog() -> EventSchemaCatalog:
    catalog = EventSchemaCatalog()
    for event_type in ("workflow_succeeded", "step_finished"):
        catalog.register(
            EventSchemaRegistration(
                event_type=event_type,
                data_schema="newsroom.workflow-event/v1",
                json_schema={
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {
                        "path": {"type": "array", "items": {"type": "string"}},
                        "step_id": {"type": "string"},
                        "index": {"type": "integer"},
                    },
                },
                current=True,
                authoritative_context_fields=("run_id", "workflow_id", "step_id"),
            )
        )
    return catalog


def test_emit_returns_committed_event_and_reads_only_from_durable_reader(
    tmp_path: Path,
) -> None:
    emitter = _emitter(tmp_path)

    accepted = emitter.emit_default(
        "workflow_succeeded",
        {"path": ["collect", "report"]},
        occurred_at=NOW,
        event_id="evt-scoped-accepted",
    )

    assert accepted.stream_sequence == 1
    assert emitter.list_events() == [accepted]
    compat = emitter.list_compat_events()
    assert [envelope.event_id for envelope in compat] == [accepted.event_id]
    assert compat[0].sequence == accepted.stream_sequence
    assert emitter.last_accepted_sequence == 1
    assert emitter.last_accepted_event_id == "evt-scoped-accepted"
    assert not hasattr(emitter, "_events")
    assert not hasattr(emitter, "_records")
    assert not hasattr(emitter, "_envelopes")


def test_caller_mutation_cannot_change_accepted_payload_or_context(tmp_path: Path) -> None:
    emitter = _emitter(tmp_path)
    payload = {"path": ["collect"]}
    context = BusinessContext(
        run_id="run-scoped",
        workflow_id="workflow-scoped",
        step_id="collect",
    )

    accepted = emitter.emit(
        "workflow_succeeded",
        payload,
        business_context=context,
        occurred_at=NOW,
    )
    payload["path"].append("mutated")

    assert thaw_canonical_json(accepted.payload) == {"path": ["collect"]}
    assert accepted.business_context.step_id == "collect"
    assert emitter.list_events()[0].content_checksum == accepted.content_checksum


def test_parallel_emits_keep_per_call_step_and_trace_context_isolated(
    tmp_path: Path,
) -> None:
    emitter = _emitter(tmp_path)

    def publish(index: int):
        step_id = f"step-{index}"
        return emitter.emit_from_trace_context(
            "step_finished",
            {"step_id": step_id, "index": index},
            trace_context=TraceContext(
                run_id="run-scoped",
                workflow_id="workflow-scoped",
                step_id=step_id,
                trace_id=f"{index + 1:032x}",
                span_id=f"{index + 1:016x}",
            ),
            occurred_at=NOW,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = tuple(pool.map(publish, range(16)))

    by_step = {event.business_context.step_id: event for event in accepted}
    assert len(by_step) == 16
    for index in range(16):
        step_id = f"step-{index}"
        event = by_step[step_id]
        assert event.trace is not None
        assert event.trace.trace_id == f"{index + 1:032x}"
        assert thaw_canonical_json(event.payload)["index"] == index

    durable = emitter.list_events()
    assert [event.stream_sequence for event in durable] == list(range(1, 17))


def test_legacy_invalid_trace_is_correlation_extension_not_trace_block(
    tmp_path: Path,
) -> None:
    emitter = _emitter(tmp_path)

    accepted = emitter.emit_from_trace_context(
        "step_finished",
        {"step_id": "legacy-step"},
        trace_context=TraceContext(
            run_id="run-scoped",
            workflow_id="workflow-scoped",
            step_id="legacy-step",
            trace_id="legacy-trace",
            span_id="workflow:run-scoped",
        ),
        occurred_at=NOW,
    )

    assert accepted.trace is None
    legacy = thaw_canonical_json(accepted.extensions)["io.newsroom.legacy"]
    assert legacy == {
        "trace_id": "legacy-trace",
        "span_id": "workflow:run-scoped",
        "parent_span_id": None,
    }


def test_durable_emitter_has_no_second_compatibility_dispatch_path(tmp_path: Path) -> None:
    emitter = _emitter(tmp_path)
    accepted = emitter.emit_default(
        "workflow_succeeded",
        {"path": ["done"]},
        occurred_at=NOW,
    )

    assert emitter.list_events() == [accepted]
    assert not hasattr(emitter, "event_bus")


def test_publish_failure_is_fail_closed_without_bus_or_memory_fallback(
    tmp_path: Path,
) -> None:
    class FailingRuntime:
        def publish(self, event, *, unit_of_work=None):
            raise EventStoreUnavailableError("durable store unavailable")

    emitter = replace(_emitter(tmp_path), runtime=FailingRuntime())

    with pytest.raises(EventStoreUnavailableError, match="durable store unavailable"):
        emitter.emit_default(
            "workflow_succeeded",
            {"path": ["never-accepted"]},
            occurred_at=NOW,
        )

    assert emitter.list_events() == []


def test_payload_context_duplicate_must_equal_canonical_context(tmp_path: Path) -> None:
    emitter = _emitter(tmp_path)

    accepted = emitter.emit_from_trace_context(
        "step_finished",
        {"step_id": "step-equal", "index": 1},
        trace_context=TraceContext(
            run_id="run-scoped",
            workflow_id="workflow-scoped",
            step_id="step-equal",
            trace_id="1" * 32,
            span_id="2" * 16,
        ),
        occurred_at=NOW,
    )
    assert "step_id" not in thaw_canonical_json(accepted.payload)

    with pytest.raises(EventContextConflictError, match="step_id"):
        emitter.emit_from_trace_context(
            "step_finished",
            {"step_id": "step-conflict", "index": 2},
            trace_context=TraceContext(
                run_id="run-scoped",
                workflow_id="workflow-scoped",
                step_id="step-authoritative",
                trace_id="3" * 32,
                span_id="4" * 16,
            ),
            occurred_at=NOW,
        )


def test_recorder_facade_has_no_ledger_and_projects_durable_envelopes(tmp_path: Path) -> None:
    emitter = _emitter(tmp_path)
    recorder = WorkflowEventRecorderFacade(emitter)

    envelope = recorder.emit(
        "workflow_succeeded",
        {"path": ["done"]},
        trace_context=TraceContext(
            run_id="run-scoped",
            workflow_id="workflow-scoped",
            trace_id="1" * 32,
            span_id="2" * 16,
        ),
        occurred_at=NOW,
    )

    assert envelope.event_id == emitter.last_accepted_event_id
    assert envelope.sequence == 1
    assert recorder.list_events() == [envelope]
    assert not hasattr(recorder, "_events")


def test_run_scope_and_stream_conflicts_fail_before_publish(tmp_path: Path) -> None:
    emitter = _emitter(tmp_path)

    with pytest.raises(EventContextConflictError, match="run_id"):
        emitter.emit(
            "workflow_succeeded",
            {"path": ["wrong-run"]},
            business_context=BusinessContext(
                run_id="another-run",
                workflow_id="workflow-scoped",
            ),
            occurred_at=NOW,
        )

    with pytest.raises(EventContextConflictError, match="stream_id"):
        replace(emitter, stream_id="run:another-run")
    assert emitter.list_events() == []


def test_zero_w3c_ids_are_legacy_correlation_not_canonical_trace(
    tmp_path: Path,
) -> None:
    emitter = _emitter(tmp_path)
    accepted = emitter.emit_from_trace_context(
        "step_finished",
        {"step_id": "zero-trace"},
        trace_context=TraceContext(
            run_id="run-scoped",
            workflow_id="workflow-scoped",
            step_id="zero-trace",
            trace_id="0" * 32,
            span_id="0" * 16,
        ),
        occurred_at=NOW,
    )
    assert accepted.trace is None
    assert "io.newsroom.legacy" in thaw_canonical_json(accepted.extensions)


@pytest.mark.parametrize(
    "unsafe_trace_id",
    [
        "not safe because spaces",
        "x" * 129,
        "trace/with/path-separator",
    ],
)
def test_unsafe_legacy_trace_correlation_fails_before_durable_append(
    tmp_path: Path,
    unsafe_trace_id: str,
) -> None:
    emitter = _emitter(tmp_path)

    with pytest.raises(ValueError, match="safe correlation"):
        emitter.emit_from_trace_context(
            "step_finished",
            {"step_id": "unsafe-trace"},
            trace_context=TraceContext(
                run_id="run-scoped",
                workflow_id="workflow-scoped",
                step_id="unsafe-trace",
                trace_id=unsafe_trace_id,
                span_id="workflow:run-scoped",
            ),
            occurred_at=NOW,
        )

    assert emitter.list_events() == []
