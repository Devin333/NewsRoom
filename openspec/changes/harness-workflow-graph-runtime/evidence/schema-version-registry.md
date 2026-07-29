# Harness Graph Runtime v2 Schema Version Registry

- Registry schema: `newsroom.harness-graph-schema-version-registry/v1`
- Registry status: `locked-for-initial-implementation`
- Runtime generation: `newsroom.harness-graph-runtime/v2`
- Captured: `2026-07-29`
- Scope: OpenSpec task `1.5`

This registry fixes the initial Graph Runtime contract and event identities
before implementation. Identifiers in the companion JSON file are the
machine-readable source of truth. A disagreement between this document and the
JSON registry blocks preflight, release, and migration until corrected.

The product/runtime generation and the schema major are intentionally separate.
Harness Graph Runtime is generation v2 because it replaces the authoritative
single cursor. Each newly named graph schema starts at schema major v1 because
it has no prior serialized schema under that name. Existing canonical event
envelopes remain `newsroom.event-envelope/v2`.

## Version Rules

1. Every serialized contract carries its exact schema identity. Every recorded
   deterministic component carries its exact implementation/policy version.
2. Exact identities, including Workflow, Step, Worker, Gate, Side Effect,
   Compensation, compiler, evaluator, reducer, and policy versions, participate
   in normalized graph identity or the relevant decision/history checksum.
3. `current`, `default`, `latest`, and `stable` are forbidden aliases.
4. A compatible additive change remains within a schema major only when its
   reader policy explicitly permits it. An incompatible meaning or required
   field change receives a new major and an explicit reader/upcaster.
5. Missing, unknown, ambiguous, or incompatible identities fail before
   `RUN_CREATED` for new runs and enter typed quarantine for historical reads.
6. Runtime graph mutation never changes a pinned graph or schema identity.
7. A v2 run is written and executed by one graph engine. Compatibility means
   explicit read/upcast, never dual execution or dual write.

## Core Contract Registry

| Registry key | Exact identity | Initial writer | Reader policy |
| --- | --- | --- | --- |
| Runtime generation | `newsroom.harness-graph-runtime/v2` | Graph composition | Exact generation only |
| Graph authoring DSL | `newsroom.harness-workflow-graph/v1` | Workflow authoring | Exact v1; future versions require explicit compiler registration |
| Normalized Graph IR | `newsroom.harness-normalized-graph/v1` | Pinned graph compiler | Exact v1; no runtime patching |
| Graph state projection | `newsroom.harness-graph-state/v1` | Graph reducer | Exact v1 plus explicit legacy state reader |
| Graph scheduler decision | `newsroom.harness-graph-decision/v1` | `HarnessScheduler` | Exact v1; decision checksum required |
| Graph checkpoint | `newsroom.harness-graph-checkpoint/v1` | Checkpoint service | Exact v1 plus explicit legacy checkpoint reader |
| Graph inspection projection | `newsroom.harness-graph-inspection/v1` | Application service projector | Exact v1; security-projected only |

Required deterministic component versions:

| Component | Exact version |
| --- | --- |
| Legacy-to-graph and explicit DSL compiler | `newsroom.harness-graph-compiler/v1` |
| Pure graph evaluator | `newsroom.harness-graph-evaluator/v1` |
| Executable-node lifecycle machine | `newsroom.harness-step-lifecycle/v1` |
| Graph state reducer | `newsroom.harness-graph-state-reducer/v1` |
| Graph control policy | `newsroom.harness-graph-control-policy/v1` |
| Restricted condition policy | `newsroom.harness-graph-condition-policy/v1` |
| Deterministic merge contract | `newsroom.harness-graph-merge/v1` |

These are exact replay registrations, not package versions. A recorded history
must resolve the exact implementation or an explicit migration. It cannot run
the current implementation merely because the component ID matches.

## Canonical Graph Event Registry

Every event below uses the existing canonical envelope
`newsroom.event-envelope/v2`, the existing `run:<run_id>` stream, and the
store-assigned one-based `stream_sequence`. The event data schemas contain
bounded references and checksums rather than raw Worker, prompt, Tool, signal,
or side-effect payloads.

| Event type | Exact data schema | Required semantic boundary |
| --- | --- | --- |
| `harness_graph_created` | `newsroom.harness-graph-created/v1` | Pins runtime generation, compiler, Workflow version, Graph IR version/checksum, and initial projection checksum before execution |
| `harness_graph_decision_committed` | `newsroom.harness-graph-decision/v1` | Commits one scheduler decision with input projection checksum and exact policy versions |
| `harness_graph_node_activated` | `newsroom.harness-graph-node-activated/v1` | Commits node-instance identity, branch/iteration scope, activation ordinal, and budget reservation before dispatch |
| `harness_graph_node_terminal` | `newsroom.harness-graph-node-terminal/v1` | Commits terminal node outcome and exact gate/activity/effect references |
| `harness_graph_choice_selected` | `newsroom.harness-graph-choice-selected/v1` | Commits condition-policy version and selected branch before activation |
| `harness_graph_fork_opened` | `newsroom.harness-graph-fork-opened/v1` | Commits fork identity and stable branch scopes |
| `harness_graph_join_satisfied` | `newsroom.harness-graph-join-satisfied/v1` | Commits exact branch terminal evidence and failure policy result |
| `harness_graph_loop_transitioned` | `newsroom.harness-graph-loop-transition/v1` | Commits loop entry, continuation, exit, or exhaustion with iteration and budgets |
| `harness_graph_wait_transitioned` | `newsroom.harness-graph-wait-transition/v1` | Commits registration, resume, timeout, cancellation, timer wake, or approval evidence |
| `harness_graph_winner_selected` | `newsroom.harness-graph-winner-selected/v1` | Commits Parallel-Any winner using authoritative success transition sequence |
| `harness_graph_cancellation_transitioned` | `newsroom.harness-graph-cancellation-transition/v1` | Commits cancellation request, confirmation, or indeterminate reconciliation state |
| `harness_graph_compensation_transitioned` | `newsroom.harness-graph-compensation-transition/v1` | Commits stack push, mode entry, action scheduling, action outcome, or manual intervention |
| `harness_graph_budget_transitioned` | `newsroom.harness-graph-budget-transition/v1` | Atomically reserves, consumes, releases, or exhausts graph/run budget |
| `harness_graph_run_lifecycle_transitioned` | `newsroom.harness-graph-run-lifecycle-transition/v1` | Separates lifecycle from terminal outcome and records the projection checksum |

An implementation may use one reusable validation helper, but it may not
collapse these meanings into an untyped arbitrary payload. Any consolidation
or rename changes this locked registry and requires an explicit OpenSpec design
update before history is written.

## Existing Dependency Versions Retained

Graph Runtime does not replace these exact dependency identities:

| Dependency contract | Exact identity |
| --- | --- |
| Canonical event envelope | `newsroom.event-envelope/v2` |
| v1 Harness event data | `newsroom.harness-event/v1` |
| v1 Harness transition data | `newsroom.harness-transition/v1` |
| v1 Harness state projection | `newsroom.harness-state-projection/v1` |
| v1 Harness reducer | `newsroom.harness-state-reducer/v1` |
| v1 Harness control policy | `newsroom.harness-control-policy/v1` |
| Harness Worker activity | `newsroom.harness-worker-activity/v1` |
| Harness activity result | `newsroom.harness-activity-result/v1` |
| Deterministic history | `newsroom.deterministic-history/v1` |
| Replay activity record | `newsroom.replay-activity-record/v1` |
| Side-effect intent | `newsroom.harness-side-effect-intent/v1` |
| Side-effect decision | `decision_version = "1"` |
| Side-effect outcome | `newsroom.harness-side-effect-outcome/v1` |
| Terminal side-effect policy | `newsroom.harness-terminal-side-effect-policy/v1` |

Graph history references these identities rather than copying or silently
upgrading them.

## Legacy v1 Reader Identities

`HarnessWorkflowSpec`, `HarnessState`, `HarnessDecision`, and
`HarnessCheckpoint` currently serialize without an embedded schema identity.
Their readers must never infer a version merely because a field is absent.
Only a known v1 source adapter, manifest, event schema, or checkpoint container
may assign one of the following reader-only source identities:

| Reader source identity | Applies to | Upcast destination |
| --- | --- | --- |
| `newsroom.harness-workflow-legacy/v1` | Known legacy `HarnessWorkflowSpec.to_dict()` records | compiler `newsroom.harness-graph-compiler/v1` -> `newsroom.harness-normalized-graph/v1` |
| `newsroom.harness-state-legacy/v1` | Known legacy `HarnessState.to_dict()` records | `newsroom.harness-graph-state/v1` |
| `newsroom.harness-decision-legacy/v1` | Known legacy direct decision records | `newsroom.harness-graph-decision/v1` |
| `newsroom.harness-checkpoint-legacy/v1` | Known legacy Harness checkpoints | `newsroom.harness-graph-checkpoint/v1` |
| `newsroom.harness-event/v1` | Catalog-validated v1 Harness events | Registered v1 reducer/adapter only |
| `newsroom.harness-transition/v1` | Catalog-validated v1 transition events | Registered v1 reducer/adapter only |
| `newsroom.harness-state-projection/v1` | Embedded v1 transition state | Explicit state upcaster only |

Reader-only source identities are never emitted by the v2 writer. An
unversioned object arriving outside an allowlisted legacy source is
`unknown_version`, not legacy v1.

## v1 Status Projection

The legacy status mapping is fixed:

| v1 status | v2 lifecycle | v2 outcome |
| --- | --- | --- |
| `CREATED` | `CREATED` | `NONE` |
| `RUNNING`, `PLANNING`, `EXECUTING`, `VERIFYING`, `REPLANNING` | `RUNNING` | `NONE` |
| `WAITING_APPROVAL`, resumable `BLOCKED` | `WAITING` | `NONE` |
| `SUCCEEDED` | `COMPLETED` | `SUCCEEDED` |
| `FAILED` | `COMPLETED` | `FAILED` |
| `CANCELLED` | `COMPLETED` | `CANCELLED` |
| `HALTED` | `HALTED` | `NONE`, unless durable evidence proves `INDETERMINATE` |

The upcaster may reconstruct only facts proven by v1 Workflow, state,
transition, activity, side-effect, and checkpoint evidence. It may compile a
linear/conditional v1 workflow into Graph IR, but it may not invent parallel
branches, winners, generic Waits, loop iterations, compensation entries,
fencing generations, or missing outcomes. Missing required evidence produces
typed quarantine or incomplete-history failure.

## Bounded Compatibility Window

The support window is milestone-bounded rather than date-based. Failure to meet
an exit gate blocks completion; it does not create a permanent compatibility
promise.

### Window A: Pre-v2 write authority

- v1 remains the production writer/executor.
- v2 contracts, compiler, reducers, fixtures, and offline readers may be built.
- v2 composition and graph-aware history writes remain disabled.
- No v1 record is rewritten in place.

### Window B: v2-only write and execution with bounded v1 reads

This window begins only after graph contract, compiler, state, scheduler,
Control Plane, event catalog, checkpoint, replay, migration, and relevant
release gates authorize the cutover.

- v2 is the only writer and executor for newly accepted runs.
- supported v1 Workflow/history/state/checkpoint values are read only through
  the exact source identities and registered upcasters above.
- a v1 history is compiled/upcast into the single graph executor; it is never
  resumed by a parallel v1 engine.
- no dual write, dual execution, moving-version fallback, or v2-to-v1 downcast
  is permitted.
- rollback after a v2 write requires a graph-capable reader and leaves the run
  suspended if execution support is unavailable.

### Window C: v1 reader/upcaster retirement

Task `14.6` performs retirement only after all of these entry gates pass:

1. task `12.6` corruption, unknown-version, missing-evidence, and incompatible
   Graph migration fixtures pass;
2. task `14.4` mixed v1/v2 Research inspection, recovery, artifact visibility,
   and latest-result fixtures pass;
3. task `14.5` proves no repository caller treats `current_step_id` or run-wide
   PLAN/EXECUTE/VERIFY status as authority;
4. every supported v1 production history/checkpoint is deterministically
   migrated/read, or explicitly quarantined with retained operator evidence;
5. no production v1 writer or executor remains;
6. tasks `15.1` through `15.8` pass, including replay, fault injection,
   compile, mandatory smoke, strict validation, and rollback drills.

After those gates, task `14.6` removes the old routing executor, cursor
authority, dual paths, and migration-only readers/upcasters. Task `15.9`
records the exact removal evidence. Unsupported residual v1 input then fails
with a typed version/history diagnostic; it never invokes a legacy or live
fallback.

## Fail-Closed Compatibility Rules

- A v2 run is never read as v1, downcast to `current_step_id`, or resumed by the
  v1 executor.
- A v1 reader cannot choose the current compiler, reducer, or policy by default;
  it resolves the exact versions in this registry.
- A missing Graph checksum, projection checksum, last stream sequence, node
  identity, activity outcome, gate evidence, winner, Wait, or compensation
  reference is not synthesized.
- Historical bytes and canonical event identity are not rewritten by an
  upcaster. Upcasting produces a new in-memory/read projection or an explicitly
  authorized migration artifact.
- Replay never appends synthetic events to the source stream.
- Unknown future schema majors are quarantined rather than treated as v1 or
  current.

## Change Control

Before the first Graph history write, an identifier change requires updating
both registry files, the OpenSpec design/specs when semantics change, and the
planned fixtures. After any Graph history exists, an identifier or meaning
change requires a new schema/component version plus explicit reader/upcaster
and replay fixtures; editing this registry in place is insufficient.

The registry is implemented in `framework/harness/workflow/versioning.py` and
is checked against this machine-readable evidence by
`tests/framework/harness/workflow/test_normalized_graph_contracts.py`.
`HarnessWorkflowContractReader` requires an explicit source schema, treats v1
as readable but non-executable, and refuses unknown versions. Task `1.5` is
therefore checked; the retirement gates above remain unchanged.
