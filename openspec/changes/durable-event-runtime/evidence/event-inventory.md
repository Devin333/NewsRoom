# Durable Event Runtime Inventory

Captured at repository HEAD `f21acc861562d2dbfa0a70a40665044ecb88408c` for
OpenSpec change `durable-event-runtime`.

This inventory is the migration boundary for task 1.1. `KEEP` means the
domain or read-model responsibility remains, `ADAPT` means the implementation
must cross the canonical durable boundary, and `DELETE` means the production
path must be removed after the documented migration gate. Historical readers
and fixtures remain read-only even when a production writer is deleted.

## Canonical-boundary models and services

| Production asset | Current role | Ownership decision |
| --- | --- | --- |
| `framework.events.Event` | Typed draft with payload, metadata, time, and duplicated durable context | `ADAPT`: retain as a bounded typed input facade; canonicalize deeply and move authoritative durable context to `StoredEvent` |
| `framework.events.EventEnvelope` | Event identity, in-memory sequence, correlation, and a second copy of run/trace/workflow context | `ADAPT -> DELETE`: bounded legacy reader/projection only; reject duplicate-context conflicts |
| `framework.events.recorder.EventRecord` | Workflow emit result and raw JSONL writer (`newsroom.event_record.v1`) | `DELETE`: retain only explicit historical import fixtures/readers |
| `framework.events.EventRecorder` | Workflow writer with `_records` and `_envelopes` ledgers plus synchronous bus dispatch | `ADAPT`: replace with a scoped durable emitter; remove dual ledgers and raw JSONL authority |
| `framework.events.InMemoryEventRecorder` | Envelope collection | `KEEP`: test adapter only; never a required durable sink |
| `framework.events.InMemoryEventBus` / `EventBus` | Synchronous fail-fast callable/protocol dispatch and `_published` history | `KEEP`: test/compatibility adapter only; remove mixed payload delivery and production authority |
| `framework.events.EventPublisher` | Builds `Event` and publishes to the in-process bus | `ADAPT`: schema/security/canonical runtime input; return durable acceptance |
| `framework.events.EventSubscriber` / `FunctionEventSubscriber` | `handle(envelope) -> None` and callable shim | `ADAPT`: stable consumer identity and durable outcomes; callable shim is bounded to one migration release |
| `framework.events.EventOrderingPolicy` | Process-local counter and timestamp fallback sorting | `KEEP`: tests/compatibility only; store-owned `stream_sequence` is authoritative |
| `framework.events.EventReplay` | Direct subscriber invocation and `replay_to_bus()` | `ADAPT`: explicit rebuild/verify/redeliver modes; `DELETE` live-bus replay in production |
| `framework.events.EventFilter` | Type/source/correlation/time filtering | `ADAPT`: sequence cursor and tenant/classification-aware application query contract |
| `framework.events.TraceContext` / `TraceEvent` | Custom trace facade and diagnostic event | `KEEP/ADAPT`: W3C/OTel-compatible immutable facade; never business ordering or causation authority |

The public migration surface is exported by `framework/events/__init__.py` and
re-exported by `framework/workflow/__init__.py`. The one-release compatibility
surface is frozen by `tests/framework/events/test_imports.py`. Production
exports for framework `EventRecord`, mixed callable payloads, and live-bus
replay are deletion targets.

## Workflow writers, readers, and duplicate stores

| Path | Current responsibility | Ownership decision |
| --- | --- | --- |
| `framework/workflow/runtime/execution_context.py` | Creates `EventRecorder` and mutates shared recorder trace context | `ADAPT`: inject a scoped emitter and immutable context per append |
| `framework/workflow/runtime/runtime_event_bridge.py` | Emits workflow, edge, review, memory, and terminal facts | `ADAPT`: typed input to the canonical runtime |
| `framework/workflow/runtime/execution_loop.py` | Emits lifecycle, retry, pause, failure, and success facts | `ADAPT`: durable append before recoverable state/effect advancement |
| `framework/workflow/runtime/step_invoker.py` | Emits step, policy, safety, timeout, and retry facts | `ADAPT`: scoped append without shared context leakage |
| `framework/workflow/runtime/checkpoint_coordinator.py` | Uses `len(recorder.list_events())` as `event_offset` | `ADAPT`: committed event id and 1-based stream sequence |
| `framework/workflow/runtime/outcome_finalizer.py` | Writes raw recorder records to `run/<run_id>/events.jsonl` | `ADAPT`: deterministic redacted projection from the durable stream |
| `framework/workflow/runtime/runner.py::_index_events` | Reads JSONL after the run and appends another store | `DELETE` in the writer cutover release |
| `framework/workflow/runtime/runner.py::WorkflowEventRecord` | Runner-local storage record | `DELETE` after projection compatibility is proven |
| `framework/workflow/runtime/runner.py::LocalJsonWorkflowEventStore` | Runner-local post-run JSONL index | `DELETE` after cutover |
| `framework/workflow/runtime/runner.py::event_store_from_env` | Runner-local factory with semantics different from storage factory | `DELETE`; use the storage-owned composition entry point |
| `framework/workflow/inspection/inspector.py::WorkflowEventRecord` | Offline/public inspection projection DTO | `KEEP/ADAPT`: read model only; online reads use an application-owned durable reader |

### Workflow event aliases to register

Existing semantic names remain registered v1 aliases during migration:

```text
workflow_started
workflow_resumed
checkpoint_restored
checkpoint_created
edge_evaluated
edge_traversed
edge_rejected
human_review_decision_received
human_review_requested
human_review_paused
human_review_approved
human_review_rejected
human_review_needs_changes
agent_llm_stream_event
memory_recall
memory_write
memory_consolidate
workflow_succeeded
workflow_blocked
workflow_budget_exceeded
workflow_failed
workflow_timeout_exceeded
workflow_cancelled
workflow_loop_limit_exceeded
workflow_paused
step_started
step_succeeded
step_skipped
step_paused
step_blocked
step_failed
step_retry_scheduled
step_timeout
policy_violation
runtime_safety_violation
runner_capability_violation
```

`WorkflowRuntimeEvent` and `StepRuntimeEvent` in
`framework/workflow/runtime/state_machine.py` remain deterministic domain
commands/transitions. They are not evidence that the corresponding facts are
already durably stored.

## Storage models and adapters

| Asset | Current contract | Ownership decision |
| --- | --- | --- |
| `infrastructure.storage.events.EventRecord` | A second flat event fact model using `timestamp`, severity, redaction, and metadata | `ADAPT`: legacy adapter/projection DTO; infrastructure must not define a second canonical fact |
| `LocalJsonEventStore` | Per-run append-only JSONL with 0-based line offsets and write-time redaction | `ADAPT`: legacy import/export/read adapter; replace production local writes with SQLite |
| `PostgresEventStore` | `workflow_events`, separate `COUNT(*)` allocation and insert transactions | `ADAPT`: canonical PostgreSQL adapter with transaction-safe per-stream sequence and identity checks |
| `001_initial.sql` | Deployed `workflow_events` schema with `(run_id,event_offset)` uniqueness | `KEEP` unchanged; add an additive migration |
| `infrastructure.storage.events.event_store_from_env` | DSN selects PostgreSQL; otherwise local JSON | `ADAPT`: DSN selects PostgreSQL; otherwise local SQLite |

The legacy read API names `append_event`, `list_by_run`, `list_by_step`,
`filter_by_type`, and `stream_from_offset` remain behind a one-release adapter.
JSONL offsets remain import metadata and are never canonical sequence identity.

## Harness event ownership

| Asset | Current contract | Ownership decision |
| --- | --- | --- |
| `HarnessEvent` / `HarnessEventType` | Typed control-plane facts | `KEEP/ADAPT`: map to registered canonical schemas |
| `HarnessEventPort.record` | Event sink protocol | `ADAPT`: production composition must fail closed on durable append failure |
| `InMemoryHarnessEventPort` | Default control-plane sink | `KEEP`: tests only; not a production durable fallback |
| `HarnessEventLogEntry` / `InMemoryHarnessEventLog` | Independent in-memory history and projection | `ADAPT`: canonical projection/read model; remove memory-only authority |
| `HarnessCheckpoint` | `last_event_id` without durable stream sequence/version | `ADAPT`: stream, last applied sequence, versions, and checksum |
| `HarnessReplayReader` | Summary over caller-provided history | `ADAPT`: ordered canonical reader and durable replay reports |

Registered Harness aliases include `run_created`, `run_state_changed`,
`step_state_changed`, `phase_recorded`, `decision_recorded`, `worker_called`,
`worker_result_recorded`, `gate_evaluated`, and `checkpoint_created`.
Harness remains the sole routing and quality authority.

Agent, Tool, Memory, Worker, LLM, source, audit, and research event classes are
domain or diagnostic types. They are `KEEP` typed inputs and are adapted only
when they cross the durable boundary; they are not mechanically replaced or
made global event-store aggregates by this change.

## Offset and sequence semantics

| Name/location | Base | Current meaning | Migration rule |
| --- | --- | --- | --- |
| run JSONL line index | 0 | Legacy import position | Persist as `legacy_event_offset` only |
| inspection `line_number` | 1 | Human-readable projection line | Never a stream identity |
| local/PostgreSQL `event_offset` | 0 | Legacy store position | Map through an explicit import mapping |
| workflow checkpoint `event_offset` | 0 | Recorder list length before `checkpoint_created` | Replace with last committed event id and sequence |
| SSE enumerated `sequence` | 0 | Transport iteration index | Replace/augment with durable cursor without reinterpreting legacy `offset` |
| canonical `stream_sequence` | 1 | Authoritative per-stream order | Store-assigned, immutable, monotonic |
| consumer checkpoint | 1 | Highest contiguous terminal sequence | Scoped by subscription version and stream |

Legacy `stream_from_offset()` is inclusive. Fixtures must prove empty, first,
last, checkpoint-before-event, and resume-after-boundary cases without a skip or
duplicate.

## External response compatibility

| Surface | Frozen behavior | Required adaptation |
| --- | --- | --- |
| `RunInspectionService.list_run_events` | `run_id`, `event_count`, `events`, `events_path`; filters `event_type`, `step_id`, `limit`, `offset` | Query application durable reader; add sequence cursor, watermark, source, and projection status |
| HTTP `GET /api/v1/runs/{run_id}/events` | Existing response envelope and `run_events_not_found` / `invalid_run_events_request` errors | Preserve core fields and errors; surface unavailable/stale explicitly |
| HTTP SSE progress/event streams | Enumerated event/progress frames and done metadata | Resume with durable cursor; do not label an array index as canonical order |
| CLI `news runs events` | Service-backed JSON/text/SSE and invalid request exit status | Preserve command/core output; add status/cursor metadata compatibly |
| MCP `news.run.events` and `news://runs/{run_id}/events` | Service-backed result/resource with `run_id` and `limit` | Preserve wrapper/core data; add availability/status/sequence metadata |
| Python SDK `RunsResource.events()` | `event_type`, `step_id`, `limit`, and legacy `offset` | Preserve signature for the migration release; new cursor is additive |

Run replay, diagnostics, and timeline paths also consume the current JSONL
inspection projection and must move with the application reader, not only the
dedicated events endpoint.

## Frozen historical variants

Representative records are stored under
`tests/fixtures/events/legacy/` and cover:

1. `newsroom.event.v1` typed event nested in an envelope.
2. `newsroom.event_envelope.v1` with equal and conflicting duplicate context.
3. `newsroom.event_record.v1` flat workflow records using `occurred_at` and the
   `timestamp` alias.
4. Schema-less storage records using `timestamp`, severity, redaction metadata,
   and task/agent/tool/request identifiers.
5. Minimal flat workflow JSONL records that lack the formal framework schema.
6. Runner `_records/events` storage-shaped projections.
7. PostgreSQL rows with 0-based `event_offset` semantics.
8. Workflow checkpoint v0/v1 envelope metadata.
9. Harness event, event-log, and checkpoint shapes.
10. Invalid JSON, non-object input, unknown schemas, missing time, context
    conflicts, unsafe run ids, and same-id collisions.

## Audit commands and high-risk omissions

The inventory was produced with repository-wide searches for `EventRecord`,
`EventEnvelope`, `EventRecorder`, `events.jsonl`, `event_offset`,
`stream_from_offset`, `replay_to_bus`, event model declarations, and all
interface event routes.

The highest-risk omissions are the runner-local store/factory duplicating the
infrastructure factory; the incompatible `occurred_at`/`timestamp` readers;
four different offset/sequence bases; checkpoint creation before the
`checkpoint_created` emit; the small `EventType` enum not covering real emit
sites; MCP filters lagging HTTP/SDK; JSONL authority reused by replay and
diagnostics; and mutable recorder trace context leaking across parallel steps.

