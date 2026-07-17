# Durable Event Compatibility Release Evidence

Date: 2026-07-17

OpenSpec task: 9.3

## Release identity

- Compatibility release: `durable-event-runtime-migration-1`
- Canonical writer cutover commit: `1e3d0183`
- Durable run-query cutover commit: `dc47ce50`
- Tenant-scoped operator surfaces commit: `f6bce48f`
- This release is the single bounded migration release allowed by the PRD.
  The following deletion batch removed the expired framework publisher/replay/
  callable shims, framework `EventRecord`, the storage flat `EventRecord`, and
  the writable `LocalJsonEventStore`. Historical JSONL remains readable only
  through the bounded migration readers/upcasters.

## Read cutover

- `RunInspectionService` and `WorkflowRunner` capture one fixed durable stream
  high watermark and page the complete contiguous prefix for inspection,
  replay bundles, diagnostics, health, timelines, and run comparison.
- Online reads fail explicitly when the durable store is unavailable and never
  silently treat `events.jsonl` as authoritative.
- Deleted or tampered `events.jsonl` projections do not change online results.
  Non-event artifacts remain checksum-verified in strict replay.
- API, CLI, MCP, and SSE retain compatible response fields. HTTP returns the
  stable `503 event_store_unavailable` contract; CLI returns exit code `2`
  with a bounded availability diagnostic; MCP uses the typed, redacted event
  error family.
- New checkpoints already use durable 1-based stream sequence/event identity;
  legacy 0-based offsets remain explicitly named import metadata with boundary
  fixtures.

## Caller and consumer observation

- Repository production callers of framework `EventRecord`: zero.
- Repository production `.subscribe(...)` callers of the synchronous event bus:
  zero. Callable compatibility coverage is test-only for this release.
- Framework `EventRecord`, runner-local event stores/models/factory, post-run
  indexing, and replay-to-live-bus were removed before this release; they are
  protected by architecture/import regression tests and are not reintroduced.
- Architecture guards now require the framework and storage `EventRecord`
  definitions, public exports, writable JSONL store, `EventReplay`,
  `EventPublisher`, `FunctionEventSubscriber`, and workflow `event_bus`
  parameter chain to remain absent. The canonical workflow recorder facade is
  retained under its current non-legacy contract.
- External consumer sign-off and deployment observation are not fabricated by
  repository tests. The owned-code deletion scope in task 9.4 is complete;
  task 9.5 and the final release gate remain blocked on deployment rollback
  evidence.

## Verification

The implementation batch includes regression coverage for fixed-watermark
pagination, stream/tenant/cursor validation, store unavailability, JSONL
deletion/tampering, strict non-event artifact integrity, CLI durable fixtures,
API/CLI/MCP compatibility, and absence of all expired record/writer exports.
The deletion-focused storage and architecture suites passed before task 9.4
was marked complete. Final repository-wide command results remain part of task
10.5.
