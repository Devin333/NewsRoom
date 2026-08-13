## Context

Research dynamic analysis is already controlled by Harness TaskPlan and invokes the existing `SubAgentRuntime`, but the production composition does not inject a durable transcript store. The runtime therefore returns refs backed only by `FakeSubAgentTranscriptStore`, fabricates an output URI that has no reader, and lets `SubAgentTranscriptGate` pass on any non-empty string. `TaskResultRecord` and its lifecycle events do not carry child transcript lineage. A crash after a child finishes can consequently leave no authoritative evidence that recovery can reuse.

This change crosses framework contracts, filesystem persistence, TaskPlan verification/replay, and production composition. It must preserve the control-plane rule that the Harness decides scheduling and acceptance while subagents only produce candidate content. It must also preserve old TaskPlan result readability without presenting old in-memory transcript refs as durable evidence.

## Goals / Non-Goals

**Goals:**

- Make every production subagent attempt produce a versioned, immutable, checksum-bound transcript receipt before TaskPlan acceptance.
- Give candidate output a private durable owner and a resolvable canonical ref.
- Bind transcript, output, TaskPlan result, and TaskPlan lifecycle events to one parent/child/workflow/stage/task/attempt/subagent identity.
- Make same-identity retries idempotent, different-body retries conflict, and post-transcript crash recovery reuse the recorded outcome without calling the worker.
- Make restart, replay, scoped inspection, tamper detection, and bounded parent queries deterministic.
- Keep transcript content refs-only and bounded, with recursive secret/private-content rejection.

**Non-Goals:**

- This change does not delete `framework/agent/session` or alter `AgentLoop`; that is the subsequent retirement change.
- It does not create a general mutable agent workspace, session database, or new workflow capability.
- It does not make transcript persistence a routing, quality, authorization, memory, or publication authority.
- It does not reuse Research artifact publication/latest/quarantine semantics.
- It does not preserve implicit fake-store fallback or fabricate durable evidence for pre-v1 records.

## Decisions

### 1. Use versioned framework contracts and a typed receipt

`framework/harness/subagents` will own `SubAgentContextEvidence`, `SubAgentOutputDocument`, `SubAgentTranscript`, `SubAgentTranscriptReceipt`, and `SubAgentTranscriptStorePort`. Each document has an exact schema version, strict fields, canonical JSON checksum, `to_dict()`/`from_dict()` roundtrip, and immutable normalized collections.

The transcript identity projection contains `invocation_id`, `parent_run_id`, `child_run_id`, `workflow_id`, `stage_id`, `task_id`, `task_instance_id`, `attempt`, and `subagent_id`. `transcript_id` and output/context ids are deterministic derivatives of this projection. The invocation carries those fields directly rather than hiding them in metadata. Its `observed_at` comes from the accepted TaskPlan observation and is reused on recovery.

The receipt contains the transcript, context-evidence, and output refs/checksums plus identity, storage revision, and first commit time. `SubAgentResult` carries the receipt as typed evidence. A bare diagnostics string is not an acceptance input.

Alternatives considered: retaining a string `transcript_ref` would keep the current fabricated-ref failure mode; storing only a hash would prove content identity but would not provide a readable replay source.

### 2. Persist one immutable run-scoped attempt bundle

The production adapter in `infrastructure/storage/harness` will write one canonical JSON bundle below:

```text
<artifact-root>/<parent-run-id>/_harness/subagents/<transcript-id>.json
```

The bundle contains the bounded context evidence, candidate output document, transcript body, and receipt. `subagent-context://v1/...`, `subagent-output://v1/...`, and `subagent-transcript://v1/...` identify typed sections of that bundle. The adapter validates every ref against the embedded identity before returning content.

The writer creates and fsyncs a sibling temporary file, then publishes it with an atomic create-if-absent operation. A pre-existing bundle is read and compared: identical identity and document checksums return its original receipt; any difference raises `subagent_transcript_conflict`. The adapter never overwrites an accepted bundle.

`refs_for_parent()` derives its bounded, sorted result from that parent run directory. There is no mutable global or parent index, so an index cannot commit without its body. Path segments, symlink/junction/reparse chains, regular-file identity, schema, size, bundle revision, and document checksums are verified on every read.

Alternatives considered: two independent files plus an index introduces a cross-file crash boundary; a new global SQLite database weakens run-root retention ownership; the Research publication adapter carries unrelated latest/disposition semantics.

### 3. Store candidate output separately from the transcript body

The transcript remains an audit document and contains only refs, identity, gate evidence, budget facts, bounded reason codes, and lifecycle facts. The full candidate output lives once in `SubAgentOutputDocument`, inside the same atomic bundle but outside the transcript checksum projection. Its ref and checksum are carried by the receipt.

For a successful subagent task, `TaskResultRecord.result_ref` is the durable output ref rather than `HarnessWorkerResult.candidate_result_ref`. Failed and halted attempts retain the output ref/checksum only as rejected evidence and never expose it as an accepted result. This closes the current synthetic `subagent-output://...` and bare-hash ownership gap without duplicating a large output in the transcript and TaskPlan result document.

### 4. Make transcript verification a deterministic gate

`SubAgentRuntime` will require an explicit `SubAgentTranscriptStorePort`; fake runtime/tests must explicitly construct `FakeSubAgentTranscriptStore`. After the normal context/tool/memory/output/budget gates, the runtime builds the attempt documents, commits the bundle, reads it back, and obtains a receipt. `SubAgentTranscriptGate` then verifies the receipt through the store and checks every invocation/result identity field and output checksum.

Commit, read-back, checksum, size, or identity failure raises a typed stable reason and the original worker result is not returned as acceptable evidence. The parent TaskPlan runner records the resulting controlled halt/failure event. There is no production fallback to memory.

Gate evidence stored in the transcript is a strict projection containing exact gate id/version, deterministic input/evidence checksum, outcome, and stable reason code. Human messages and arbitrary details are excluded.

### 5. Carry typed evidence through the generic worker boundary

`HarnessWorkerResult` will gain immutable `HarnessWorkerEvidence` entries. The TaskPlan subagent adapter converts the typed receipt to a `subagent_attempt` evidence entry; diagnostics may expose a safe projection for operators but are not authoritative.

`TaskPlanResultVerifier` receives the transcript store, requires exactly one verified receipt for every resolved task with `subagent_id`, reads the output document, and compares status/output/artifact identity before executing task acceptance gates. It writes the transcript and output refs/checksums into `TaskResultRecord`. Non-subagent tasks do not manufacture transcript evidence.

Alternatives considered: placing the receipt only in `diagnostics` leaves an untyped optional map as the only lineage owner; making TaskPlan import a Research-specific result type violates framework ownership.

### 6. Version TaskPlan results and preserve explicit legacy behavior

New records use `newsroom.harness-task-plan-result/v2` and include transcript/output evidence fields in their checksum projection. `TaskResultRecord.from_dict()` recognizes the unversioned v1 shape, verifies its original checksum projection, and marks it as legacy through its schema version. It does not invent receipt fields.

When replay or recovery needs durable child evidence for a v1 subagent result, it fails with `subagent_transcript_legacy_unavailable`. Non-subagent v1 results remain structurally readable. This is a reader migration, not a compatibility runtime or fake ref resolver.

### 7. Reuse committed outcomes at the transcript-to-result crash boundary

The store provides a bounded identity lookup in addition to the minimum write/read/verify API. `SubAgentRuntime.invoke()` checks for an existing valid receipt before calling the worker and reconstructs the prior `SubAgentResult` from its output document.

The TaskPlan stage also receives a dedicated result-recovery callback. Before scheduling, it asks that callback only for already active subagent attempts. If a committed receipt exists, the callback returns the reconstructed candidate, normal TaskPlan verification creates the same result record, and the durable store reconciles its event/projection. A missing receipt returns no result and never causes the recovery callback to execute a live worker. Normal bounded retry/reclaim policy remains Harness-owned.

This directly covers a crash after receipt commit but before TaskResult append. Existing TaskPlan reconciliation continues to cover result-document/event and result/terminal-event boundaries.

### 8. Verify transcript evidence during replay

TaskPlan result and terminal event payloads carry `transcript_ref`, `transcript_checksum`, `subagent_output_ref`, and `subagent_output_checksum`. Replay compares event, record, accepted plan, and attempt identity, then asks the transcript store to verify the receipt and output document. Replay and recovery never call a subagent, LLM, tool, retrieval, memory write, or publication adapter.

If a required ref is missing, corrupt, fabricated, mismatched, or legacy-unavailable, replay fails closed with a typed history diagnostic. Checkpoints include the versioned result checksums, so the added lineage participates in checkpoint verification without embedding transcript bodies.

### 9. Apply refs-only security and bounded observability

Transcript construction uses an exact allowlist. Nested forbidden keys and secret-like values are rejected recursively from gate evidence, redaction facts, warnings/errors, events, and refs. Warnings/errors become bounded stable reason codes. The transcript defaults to at most `1 MiB`; the separate output document and total bundle also have explicit production limits. Oversize content fails instead of being silently truncated.

The adapter emits sanitized stable observations for commit success/failure, verification failure, conflict, corruption, byte count, latency, and recovery reuse. Payloads contain only identity, refs, checksums, sizes, durations, and reason codes. Scoped transcript reading remains behind application/inspection authorization; workers and sibling subagents receive neither `refs_for_parent()` nor transcript bodies.

## Risks / Trade-offs

- [Filesystem does not support atomic hard-link publication] -> Fail startup/commit as `subagent_transcript_store_unavailable`; contract tests exercise Windows and Linux semantics and no overwrite fallback is allowed.
- [Output document can be larger than transcript] -> Enforce a separate configurable output/bundle limit and require callers to publish larger data through an existing canonical artifact owner.
- [A malicious operator can rewrite both body and embedded receipt] -> TaskPlan events retain the original checksums; verification always uses the externally recorded receipt, not only the embedded copy.
- [Legacy result fixtures lack transcript lineage] -> Preserve v1 checksum readability but return a typed legacy-unavailable diagnostic when durable subagent evidence is required.
- [Recovery callback accidentally executes live work] -> Give recovery a separate read-only method and test it with worker/tool/memory/publication call counters fixed at zero.
- [Parent directory scan grows] -> Keep evidence run-scoped, enforce a configured maximum attempts per query, and reject unbounded scans.

## Migration Plan

1. Add v1 subagent evidence contracts, explicit fake store behavior, and v2 TaskPlan result reader/writer.
2. Add the immutable filesystem adapter and restart/concurrency/tamper/security contract tests.
3. Wire typed receipt verification, durable output ownership, TaskPlan result/events, replay, and recovery reuse.
4. Inject the production adapter under the configured artifact root and remove all implicit fake construction.
5. Run targeted tests, Research dynamic integration, compile, mandatory smoke, and strict OpenSpec validation.
6. Commit and normally archive this change so `harness-runtime` and `harness-task-plan` become the replacement contract.

Rollback reverts the production wiring and contracts together. Production must halt dynamic subagent admission if durable storage is unavailable; rollback must not reactivate an implicit fake store while claiming replay durability.

## Open Questions

None. The output owner, atomic bundle, legacy reader, and receipt-to-result recovery boundary are resolved by this design.
