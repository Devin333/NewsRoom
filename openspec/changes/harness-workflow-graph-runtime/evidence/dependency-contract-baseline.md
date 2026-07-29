# Harness Workflow Graph Runtime Dependency Contract Baseline

- Evidence schema: `newsroom.harness-graph-dependency-baseline/v1`
- Captured: `2026-07-29`
- Scope: OpenSpec tasks `1.1` and the dependency side of `1.5`
- Repository branch at audit: `main`
- Repository HEAD at audit: `46a9a2ea51305a03400b690f7002380ad2fbe34a`
- Repository tree at audit: `e504b8be194187564792f52b11559cb83d53bc12`

This document freezes the dependency facts that Graph Runtime development may
consume. It does not mark task `1.1` complete, qualify a release, or authorize a
production cutover. The audit was performed in a dirty working tree. Committed
Git identities are authoritative release identities; hashes for uncommitted
files are diagnostic fingerprints only.

## Readiness Summary

| Dependency change | OpenSpec status | Exact release or candidate identity | Contract development | Production Graph cutover |
| --- | --- | --- | --- | --- |
| `durable-event-runtime` | `52/55`, `in-progress` | verified candidate `89594289fd3e967633c3ed22e750ed72126631df`; latest durable-specific evidence commit `d5897b1980312d6414fb7670a769dae5b4e8f091` | Allowed against the exact contracts below | Not qualified for Parallel, Wait, Compensation, legacy deletion, or a general production-ready claim |
| `framework-runtime-safety-hardening` | `0/38`, `in-progress` | no committed dependency release; current implementation is an uncommitted workspace candidate | Contract integration and tests may continue provisionally | Hard blocked for physical concurrency, uncertain-timeout retry, cancellation replacement, and compensation activity dispatch |
| `harness-side-effect-authority-closure` | `51/51`, `complete` | implementation `7caadd86ac037d574f31856ec8553503a70bc938`; completion evidence `46a9a2ea51305a03400b690f7002380ad2fbe34a` | Allowed | Original effect decision/outcome authority is qualified; Graph compensation ordering and compensation contracts remain Graph-owned work |

`Sequence` and deterministic `Choice` contract, compiler, fixture, reducer, and
equivalence development may proceed. This baseline does not authorize v2 write
authority. A Sequence/Choice production cutover must independently satisfy the
Graph tasks and release gates that own graph schemas, state, replay, recovery,
migration, and rollback.

Physical Parallel, durable Wait, and Compensation production cutover are
explicitly blocked until the dependency gates in this document are satisfied.

## Durable Event Runtime

### Pinned contract identities

| Contract | Exact identity | Evidence source | Status |
| --- | --- | --- | --- |
| Canonical stored envelope | `newsroom.event-envelope/v2` | `framework/events/canonical.py` | Satisfied |
| Harness event data | `newsroom.harness-event/v1` | `framework/events/schema/catalog.py` | Satisfied for v1 history |
| Harness transition data | `newsroom.harness-transition/v1` | `framework/harness/control_plane/transition.py` | Satisfied for v1 transitions |
| Harness state projection | `newsroom.harness-state-projection/v1` | `framework/harness/control_plane/transition.py` | Satisfied for v1 state projection |
| Harness reducer | `newsroom.harness-state-reducer/v1` | `framework/harness/control_plane/transition.py` | Satisfied |
| Harness control policy | `newsroom.harness-control-policy/v1` | `framework/harness/control_plane/transition.py` | Satisfied |
| Harness Worker activity | `newsroom.harness-worker-activity/v1` | `framework/harness/control_plane/activity.py` | Satisfied |
| Harness activity result | `newsroom.harness-activity-result/v1` | `framework/harness/control_plane/activity.py` | Satisfied |
| Deterministic history | `newsroom.deterministic-history/v1` | `framework/events/runtime/history.py` | Satisfied |
| Replay activity record | `newsroom.replay-activity-record/v1` | `framework/events/runtime/activities.py` | Satisfied |

The available runtime provides the required canonical `StoredEvent`,
store-assigned per-stream sequence, `EventSchemaCatalog`, exact-only replay
version registry, recorded activity result resolution, checkpoint/replay ports,
and side-effect-free history verification. `ExactVersionRegistry` explicitly
forbids a `latest` fallback, and recorded activity resolution explicitly
forbids live activity fallback.

### Open release blockers

The following `durable-event-runtime` tasks remain open:

- `9.5`: external rollback qualification and compatibility authority chain;
- `10.4`: final strict, compile, smoke, all-change, and diff validation after
  the release evidence is complete;
- `10.5`: final implementation status and evidence update.

The tracked compatibility evidence remains
`AWAITING_EXTERNAL_AUTHORITY_ACTIVATION`. It has no activated positive trust
epoch, no pinned governance/observer/consumer-owner roots, no signed D/A/B/C
chain, and no independent completed rollback qualification. Repository tests
cannot manufacture those external facts.

Consequences for Graph Runtime:

- graph contract and offline replay development may consume the pinned event
  contracts;
- graph events must extend the existing `run:<run_id>` stream and canonical
  catalog rather than creating a second envelope, store, sequence, or replay
  engine;
- Parallel winner, Wait registration/resume, Compensation order, and graph
  lifecycle write cutovers may not claim production qualification while these
  release gates remain open;
- legacy event authority may not be deleted based on repository-only evidence.

## Framework Runtime Safety Hardening

### Provisional workspace contract

The current working tree contains a coherent but unreleased implementation of:

- immutable attempt identity with `attempt_id`, stable `idempotency_key`,
  positive `fencing_token`, deadline, and cooperative cancellation;
- `AttemptSupervisor` with bounded cancellation grace,
  `termination_confirmed`, and `indeterminate` outcomes;
- shared total-attempt budgets preventing nested Tool/Step retry multiplication;
- Workflow attempt buffer overlays and stale-fence rejection;
- Redis lease identity, renewal, monotonically increasing attempt/fencing
  values, and guarded terminal transitions;
- Worker handler exposure of lease-derived idempotency and fencing context.

The private Redis implementation marker `_LEASE_SCRIPT_VERSION = "v1"` is not
a public dependency version. No exported attempt contract version or committed
change identity exists yet.

Diagnostic fingerprints for the audited provisional candidate are:

| Source | SHA-256 |
| --- | --- |
| `framework/shared/attempts.py` | `ebcb49b59dbb132bdf73ef418f07c10911b50c160d69adc2a6e973b3685332ec` |
| `framework/tool/runtime/timeout.py` | `b0af934473587ada428664ec89326c1f66198f685390e280c82194e624eadb9a` |
| `framework/tool/runtime/executor.py` | `20bc8fe196f0acbe8422b72dbde15d8053159ac29a7967f6e3db9687f39e5e62` |
| `framework/workflow/runtime/step_invoker.py` | `f859ae80f8530a322d355e45f740e4f2bbee350a52efa7e95f34fb07b2252061` |
| `framework/workers/queue/base.py` | `1ea6beec066bfa3536973c56be56ce9afe64df434db7784967bbbcd7a9444f70` |
| `infrastructure/storage/workers/redis_queue.py` | `0491607c4ba6101273e839276caee33ebf05aa5dcf7f41aa3ba366faeadeac20` |

These hashes permit review of the audited candidate but do not turn it into a
release. Task `1.1` cannot record Runtime Safety as a satisfied production
dependency until all of the following exist:

1. a committed immutable Git identity for the dependency implementation;
2. an exported exact attempt-safety contract version, or a committed API
   baseline explicitly pinned by Graph Runtime;
3. completed Tool, Workflow, Redis lease, Worker renewal, error-boundary, and
   composition tasks with focused and broad verification;
4. successful strict OpenSpec validation, compile, mandatory smoke, and the
   required concurrency/fault-injection checks;
5. a Harness activity capability contract that exposes termination,
   idempotency, fencing, and reconciliation readiness to graph preflight.

Until then, Graph preflight must not permit physical concurrency for an
activity or side effect merely because it has an idempotency-looking string.
An explicit physical-concurrency requirement with no safe capability proof
must fail before `RUN_CREATED`. A graph that does not require physical
concurrency may remain logically parallel and use stable serial dispatch only
after the Graph runtime itself is implemented and validated; serial dispatch is
not permission to retry an unconfirmed attempt.

## Harness Side-Effect Authority Closure

### Pinned contract identities

| Contract | Exact identity | Status |
| --- | --- | --- |
| Side-effect intent | `newsroom.harness-side-effect-intent/v1` | Satisfied |
| Authority decision | `decision_version = "1"` | Satisfied |
| Side-effect outcome | `newsroom.harness-side-effect-outcome/v1` | Satisfied |
| Terminal side-effect policy | `newsroom.harness-terminal-side-effect-policy/v1` | Satisfied |
| Handler binding | exact `<handler-id>@<version>` | Satisfied; moving aliases are rejected |

The completed change provides exact instance-scoped handler resolution,
post-VERIFY durable authorization, approval binding, stable effect
idempotency, bounded effect attempts, durable outcome read-back, candidate /
prepared / quarantine / accepted isolation, and offline replay without live
handler invocation. `SQLiteHarnessSideEffectStore` is the single-host durable
implementation used by Research composition.

The dependency deliberately does not provide Graph compensation semantics.
Graph Runtime must add exact Compensation binding, stack, activity, outcome,
and event contracts. In particular, `HarnessSideEffectOutcome.committed_at`
and SQLite row order are not authoritative compensation order. The Graph
compensation entry must reference the canonical outcome event's durable
`stream_sequence` and sort by that sequence in reverse order.

## Unsafe Fallback Policy

The following rules are mandatory before any v2 production write:

1. Canonical event append, graph decision, transition, and projection failure
   fail closed before state advancement or activity dispatch. In-memory event
   lists and JSONL are not a durable authority.
2. Missing recorded Worker, Tool, MCP, retrieval, timer, signal, side-effect,
   or compensation outcomes fail replay with a typed diagnostic. Replay never
   calls a live producer to fill a gap.
3. Unknown or missing graph, schema, compiler, evaluator, reducer, policy,
   Worker, Gate, Side Effect, or Compensation versions fail preflight or enter
   explicit history quarantine. Moving aliases are forbidden.
4. Physical concurrency requires explicit cancellation, termination,
   idempotency, fencing, and reconciliation capabilities. A timeout with
   unconfirmed termination cannot overlap a retry or replacement effect.
5. Production Wait requires a durable scope-bound registration and signal
   inbox. Process memory, current wall-clock reconstruction, and unscoped
   approval lookup are forbidden fallbacks.
6. Production side effects require an exact handler registry and durable
   decision/outcome store. An in-memory side-effect store is test-only.
7. Compensation order comes from canonical stream sequence, never timestamp,
   thread completion order, static graph order, or local store row order.
8. `LocalRuntimeDiagnosticFallback` remains permitted only as a bounded safe
   diagnostic sink. It never becomes state, event, replay, or decision
   authority.

## Verification Evidence

The audit ran the following focused checks against the captured working tree:

```text
Durable Event contract/replay selection: 208 passed
Side Effect contract/authority/recovery selection: 35 passed
Provisional Runtime Safety attempt/overlay/Redis selection: 22 passed
```

All four relevant changes passed strict specification validation:

```text
openspec validate durable-event-runtime --strict
openspec validate framework-runtime-safety-hardening --strict
openspec validate harness-side-effect-authority-closure --strict
openspec validate harness-workflow-graph-runtime --strict
```

The Safety result is development evidence only because the tested files are
uncommitted and the change remains `0/38`. The Durable Event result proves the
selected contract code, not the missing external authority or release facts.

## Exit Conditions

This baseline must be refreshed before task `1.1` can be checked when any of
the following changes:

- repository HEAD or a dependency release identity;
- a pinned schema, reducer, policy, activity, decision, or outcome version;
- Runtime Safety's provisional source hashes;
- an OpenSpec dependency completion status;
- the Durable Event external authority/rollback qualification state;
- the production cutover disposition.

Final task `15.9` must cite the refreshed dependency manifest and must not reuse
this captured status if later implementation or release evidence supersedes it.
