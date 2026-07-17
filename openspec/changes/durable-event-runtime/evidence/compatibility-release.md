# Durable Event Compatibility Release Evidence

Date: 2026-07-17

OpenSpec task: 9.3

Status: AWAITING_EXTERNAL_OBSERVATION

## Release candidate identity

- Compatibility release candidate: `durable-event-runtime-migration-1`
- Deployable pre-deletion commit: `42a8636cd72aea0c466126fc5f2d69c55db1a1d6`
- Deletion commit: `570f840c7df3870841c93e37480d7a53a67921dd`
- Canonical writer cutover commit: `1e3d0183`
- Durable run-query cutover commit: `dc47ce50`
- Tenant-scoped operator surfaces commit: `f6bce48f`
- Commit `42a8636...` is the last commit before compatibility-path deletion and
  is the only eligible build for the single bounded migration release allowed
  by the PRD. The immediately following commit `570f840c...` removes the
  expired framework publisher/replay/callable shims, framework `EventRecord`,
  the storage flat `EventRecord`, and the writable `LocalJsonEventStore`.
- These commits freeze the release sequence but do not prove that the
  compatibility candidate was deployed or observed. No GitHub environment,
  deployment, release, tag, immutable build digest, or external evidence URI
  currently binds `durable-event-runtime-migration-1` to a real deployment.

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
- Repository search proves only owned-caller cleanup. It cannot prove that
  unknown external consumers stopped depending on the flat record contract.
- External consumer sign-off and deployment observation are not fabricated by
  repository tests. The owned-code deletion implementation in task 9.4 is
  complete, but its release qualification remains pending until the candidate
  is observed before the deletion build is deployed.

## Required external observation

The release gate requires all of the following evidence from systems or owners
outside this repository:

1. An immutable build or image digest produced from full commit
   `42a8636cd72aea0c466126fc5f2d69c55db1a1d6`.
2. A deployment record containing the environment, deployment identifier,
   deployment time, and externally resolvable evidence URI.
3. A bounded observation window with real query, checkpoint, and projection
   records, including run/request identity, durable sequence, projection high
   watermark, and projection checksum.
4. An external-consumer inventory and owner sign-off covering API, CLI, MCP,
   SDK, and SSE consumers. A zero-consumer result still requires an independent
   registry or owner attestation.
5. A retention-locked or content-addressed external record binding the release
   digest, observation window, results, signatory identity, and evidence
   checksum.
6. Only after items 1-5 pass, a deployment record for deletion commit
   `570f840c7df3870841c93e37480d7a53a67921dd` or a descendant deletion build.

The rollback approval, deployment attestation, and release qualification chain
for task 9.5 remains separately required. Neither chain substitutes for the
other.

## Verification

The implementation batch includes regression coverage for fixed-watermark
pagination, stream/tenant/cursor validation, store unavailability, JSONL
deletion/tampering, strict non-event artifact integrity, CLI durable fixtures,
API/CLI/MCP compatibility, and absence of all expired record/writer exports.
The deletion-focused storage and architecture suites passed before task 9.4
was marked complete. These local results qualify the code path only; they do
not complete the external observation above. Final repository-wide command
results remain part of task 10.5.
