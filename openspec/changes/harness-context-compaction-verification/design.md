## Context

`framework/harness/context` already models six ordered segments, a stable prefix, a dynamic tail, budgets, snapshots, and compression records. The implementation is nevertheless an MVP: `ContextCompressor.compress_segment()` slices a summary string in half, divides `token_estimate` by two, creates an artifact-looking URI without writing an artifact, and records a hard-coded passing loss gate. `ContextAssembler` compresses every dynamic segment and immediately emits `context_compression_verified` without rerunning `ContextBudgetGate`, structure, provenance, privacy, evidence, or replay integrity gates.

Change 1 established deployment-bound physical preparation and admission in `framework/llm/context` and `LLMRouter`. This change owns the semantic transformation that may happen before a new logical request is prepared. It must preserve the architectural boundary: the LLM can generate a summary candidate; Harness decides plans, protection, verification, promotion, retry/replan/halt, and durable commit.

The main stakeholders are Harness/workflow authors, Research workers and evidence owners, operators/replay reviewers, artifact/event store owners, LLM routing owners, and evaluation owners. Existing serialized context records and tests require an explicit legacy-read migration rather than being silently reinterpreted as verified evidence.

## Goals / Non-Goals

**Goals:**

- Parse semantic context into immutable, ordered, group-safe units with protected-content and tool-transaction semantics.
- Produce deterministic, bounded, replayable compaction plans using registered typed actions.
- Prefer reversible/ref-based and extractive evidence actions before optional generative summary actions.
- Validate summary candidates against source groups, claims, refs, omissions, conflicts, and tool outcomes.
- Re-run every deterministic semantic gate plus deployment-aware physical preparation after any transformation.
- Commit source/result snapshots, action results, aggregate gate evidence, and verdicts through canonical Harness durability owners before dispatch.
- Preserve legacy context evidence for audit while preventing it from authorizing recovery or provider calls.

**Non-Goals:**

- Implement provider tokenizers, model routing, cache policy, or provider overflow handling; Change 1 owns those concerns.
- Migrate every production LLM callsite; Change 3 owns convergence.
- Promote a learned compressor or define release thresholds; Change 4 owns held-out evaluation and promotion.
- Modify source evidence, durable memory, tool results, or artifacts in place.
- Guarantee that every protected context can fit every model. Typed fail-closed outcomes are valid results.
- Let an LLM summary or evaluator decide quality pass/fail or the next Harness state.

## Decisions

### 1. Semantic groups replace segment-local string mutation

Add immutable `ContextGroup` and `ContextGroupMember` models. A group has a stable checksum-derived id, `group_kind`, ordered member refs, source/provenance refs, protection reasons, reconstruction policy, task/query binding, and version. Initial kinds cover system instruction, workflow/current task, output contract, run/retry state, tool transaction, evidence, conversation turn, memory/reference, reconstructable material, and authorized tool schema.

Existing six `ContextSegment` values remain an assembly envelope and migration input. A materializer deterministically expands them and typed worker inputs into groups. A segment summary string is never a valid substitute for ordered group members.

Alternative considered: add more booleans to `ContextSegment`. Rejected because message/tool atomicity and evidence spans require ordered nested membership and explicit source binding, not segment-wide flags.

### 2. Tool calls and results are one transaction boundary

A `ContextToolTransaction` validator groups the assistant call and its ordered results. Completed reconstructable transactions may be removed or replaced only as a whole. Pending, unresolved, failed-with-required-state, or authorization-relevant transactions are protected. The validator runs during source materialization and after every action.

Alternative considered: trim by valid start/end roles. Rejected because role boundaries do not prove call id pairing, result completeness, or pending state.

### 3. Trusted versioned policy produces deterministic plans

`ContextCompactionPolicy` defines action order and all bounds. `ContextCompactionPlanner` accepts only an immutable source snapshot, current task/query binding, protection state, initial physical-admission evidence, and policy. It returns a checksum-derived `ContextCompactionPlan`; it never invokes an LLM or mutates context.

Plans contain ordered `ContextCompactionAction` values and explicit preconditions. Registered executors implement:

```text
DROP_RECONSTRUCTABLE_GROUP
REPLACE_WITH_REFERENCE
REDUCE_AUTHORIZED_TOOL_SET
SELECT_EVIDENCE_SPANS
COMPACT_OLD_CONVERSATION
SUMMARIZE_GROUPS
```

Reversible actions are selected first. Every action targets complete group ids. Unknown actions fail at composition. Request/worker metadata cannot change policy or protection.

Alternative considered: keep a strategy string and dispatch on it inside the assembler. Rejected because strategy names do not establish implemented semantics, bounds, preconditions, or replay identity.

### 4. Execution is a bounded Harness state machine

`ContextCompactionRuntime` follows:

```text
SOURCE_SNAPSHOT
  -> PLAN
  -> APPLY_ACTION (bounded)
  -> MATERIALIZE_RESULT
  -> VERIFY
  -> COMMIT_VERIFIED | REJECT
```

The runtime tracks action, summary-call, replan, LLM-call, token, cost, and turn budgets. It returns a typed `ContextCompactionOutcome`. A failed gate can trigger only existing bounded Harness replan/fallback/halt policy. No internal “compress until it fits” loop exists.

Alternative considered: planner callbacks decide when enough content has been removed. Rejected because callbacks obscure termination, side effects, and replay behavior.

### 5. Evidence compaction is extractive before generative

`SELECT_EVIDENCE_SPANS` operates on evidence ids and span refs bound to the current task/query. It retains required citations, source/lineage refs, conflicts, and a structured omission report. It cannot invent a ref. Conversation compaction retains a policy-defined recent tail of complete turns/tool transactions.

Generative summarization is used only when policy permits it and reversible/extractive actions are insufficient. This implements evidence-first behavior without embedding a learned compressor in core Harness.

Alternative considered: use one general LLM summary for evidence and conversation. Rejected because evidence grounding and tool-state truth require different deterministic checks.

### 6. Summary workers return candidates through a port

Define `ContextSummaryWorker` as a replaceable port. Its structured result is `ContextSummaryCandidate`:

```text
summary_artifact_ref
covered_group_ids
source_refs
claims -> supporting_refs
omitted_topics
unresolved_questions
tool_outcomes
loss_risk
worker/model/schema revisions
```

The artifact port stores summary content and returns a real checksum-bound ref. Durable context records/events contain refs and bounded metadata, not summary bodies. Unsupported authority fields are rejected.

Alternative considered: allow the worker to return a ready `ContextGroup`. Rejected because that would let worker output choose protection, identity, and promotion semantics.

### 7. Post-compaction VERIFY consumes Change 1 through a port

Harness does not import or reimplement provider tokenizers. Define a `ContextPhysicalAdmissionVerifier` port that accepts the immutable result materialization plus resolved deployment/profile identity and returns a bounded prepared-request projection: payload fingerprint, component count, effective budget, admission, and revisions. Composition adapts this port to Change 1's `LLMRequestPreparer`/router preparation contract.

`ContextCompactionVerifier` runs all gates against the same source/result snapshot ids:

```text
group structure and order
protected content
tool transaction integrity
source/provenance integrity
evidence coverage and loss
action/summary/replan budgets
snapshot/checksum integrity
deployment-aware physical admission
```

Every gate result uses the existing versioned Harness gate evidence convention, including gate id/version, input ref, result ref, reason code, and checksum. Only the aggregate verdict authorizes promotion.

Alternative considered: reuse `ContextBudgetEstimator.token_estimate` as the final gate. Rejected because it is caller-owned semantic metadata and cannot prove the actual provider payload fits.

### 8. Snapshots and records are immutable checksum-bound artifacts

Source and result snapshots receive checksum-derived ids and explicit schema revisions. A new versioned `ContextCompressionRecord` contains plan/action results, before/after physical counts, retained/removed/replaced/protected ids, reconstruction/source/summary refs, loss report, complete gate evidence, aggregate verdict, profile/tokenizer/normalizer revisions, and reason code.

The current `CompressionRecord` shape remains readable as legacy evidence. Its hard-coded boolean gates and artifact-looking strings are never upgraded implicitly. Replay labels it `legacy_unverified`.

Alternative considered: mutate the existing snapshot in `ContextSnapshotStore.envelopes`. Rejected because in-place mutation destroys source/result auditability and crash recovery boundaries.

### 9. Canonical Harness durability is the commit authority

The runtime projects plan, action, candidate, verified, and rejected events through the existing canonical Harness event/transcript port. The verified event references source snapshot, result snapshot, record, aggregate gate evidence, and physical admission evidence. Result promotion and provider-dispatch authorization occur only after durable append succeeds.

Local `assembler.events` may remain as an explicitly injected test sink during migration but is not a second production event store.

Alternative considered: create a context-specific event repository. Rejected because it would split replay truth from the Harness transcript.

### 10. Replay validates pinned facts and never recomputes

Replay resolves pinned schema/policy/profile/gate versions and validates snapshot/plan/record/artifact checksums and cross-refs. It returns the recorded verdict with `side_effects_replayed=false`. It never calls the summary worker, reruns actions, invokes tools/providers, writes memory, or publishes artifacts.

Missing or malformed refs yield typed integrity failures. Legacy evidence remains inspectable but cannot resume after a supposedly verified boundary.

## Risks / Trade-offs

- **[Conservative protection leaves context unable to fit]** -> Return `PROTECTED_CONTEXT_EXCEEDS_WINDOW`; permit only explicit workflow redesign or an allowed larger deployment, never silent deletion.
- **[Group materialization duplicates old segment concepts during migration]** -> Treat segments as compatibility input only; new planner/runtime consume groups and versioned snapshots.
- **[Summary validation cannot prove every semantic fact]** -> Use structural/source/claim/evidence gates as deterministic minimums, keep generative summary opt-in, and defer learned-compressor promotion to Change 4 held-out evaluation.
- **[Artifact or event append fails after expensive summary work]** -> Do not promote; retain rejected diagnostic refs when safely committed and let bounded Harness policy decide retry/halt.
- **[Physical verifier and Harness materialization drift]** -> Require result snapshot id and materialization revision in the prepared projection; verify the same fingerprint before dispatch.
- **[Large records/events expose sensitive text]** -> Persist ids, refs, hashes, counts, reason codes, and gate metadata only; artifact access follows existing authorization.
- **[Concurrent cache stream work changes router contracts]** -> Keep Change 2 behind the Harness physical-verifier port; it does not modify router/cache ownership.

## Migration Plan

1. Add group, protection, transaction, policy, plan/action, candidate, result, and record models with strict versioned serialization.
2. Add deterministic materializer and validators; keep existing segments as an input adapter.
3. Add planner and non-generative action executors with bounded state tracking and adversarial unit tests.
4. Add the summary worker/artifact ports and candidate validators; use fakes in tests and no default production summary worker until composition is explicit.
5. Add aggregate post-compaction gates and the physical-admission verifier adapter to Change 1.
6. Replace `ContextAssembler`'s unconditional compression path with the bounded runtime; remove fabricated summaries and false verified events.
7. Add immutable source/result snapshot and record persistence through existing artifact/event/transcript ports; extend replay and corruption tests.
8. Migrate Research context composition and run integration/smoke tests. Legacy records stay readable as `legacy_unverified`.
9. Roll back by disabling compaction policy and failing closed on over-budget semantic context. Do not restore string truncation or treat legacy records as verified.

## Open Questions

- The first implementation can use the existing artifact publisher/store abstraction for summary and snapshot refs; the exact production binding must be selected from the live composition tree during implementation rather than adding a context-owned store.
- Exact evidence-span selection policies vary by Research task. Core will define the deterministic port and required invariants; task-specific ranking remains in Research composition.
