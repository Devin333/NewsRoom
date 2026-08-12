## Context

The live tree contains three mutable cumulative LLM budget implementations. `framework.llm.budget` reserves rough prompt tokens and settles provider usage/pricing; `framework.agent.runtime.llm` has a weaker copy used by direct AgentLoop calls; `framework.workflow.governance.budget` has another copy combined with legitimate tool and wall-time tracking, and its resume helper writes `_usage` directly. `LLMRouter` and `AgentLoop` can both account for one response, while cache, fallback, stream, and failure paths infer accounting through loosely related metadata.

Stage 24 now provides deployment-aware prepared input counts, and stage 23 provides structured cache metadata. Stage 19 owns canonical event envelopes, schema validation, stores, and replay mechanics. Stage 22 owns retry credits, deadlines, leases, and indeterminate attempt recovery. This change consumes those contracts without absorbing their ownership.

The U10 live-tree parity audit in `evidence.md` proves that cumulative LLM calls/tokens/cost overlap and can converge. It also proves that Workflow tool/wall-time, Agent loop/output/stall, per-call provider limits/pricing, context capacity, and retry/deadline accounting must remain distinct.

## Goals / Non-Goals

**Goals:**

- Establish one canonical cumulative LLM ledger with strict immutable values, `Decimal` cost, stable reason codes, explicit scopes, and read-only views.
- Linearize admission and reservation under concurrency and make reserve/settle/release delivery idempotent by operation identity.
- Give router, cache, fallback, stream, AgentLoop, Workflow, subagent, checkpoint, and replay paths one lifecycle contract.
- Restore from versioned public snapshots and replay canonical budget events without invoking an LLM, provider, cache, or tool.
- Preserve Harness as the only route/quality/approval/publication decision owner.

**Non-Goals:**

- Turning retry credits, tool calls, wall time, context windows, loop iterations, stall detection, diagnostics, or redaction into generic ledger dimensions.
- Selecting providers, retries, fallback routes, replan, approval, quality verdicts, publication, or memory writes in the budget package.
- Providing a distributed quota service in this change. The canonical ledger is process-local and thread-safe; durable facts support recovery, not cross-process linearizability.
- Rewriting Research, Paper, or RAG business budget policy.

## Decisions

### 1. The canonical owner is `framework/governance/budget`

The package owns cumulative `llm_calls`, input, output, reasoning, cached-input tokens, and estimated USD cost because those facts are consumed across LLM, Agent, Workflow, and Harness boundaries. It has no imports from Agent, Workflow, Business, Interfaces, or Infrastructure. LLM-specific normalization and pricing remain in `framework/llm/budget`; Workflow and Agent retain their behavioral limits.

Alternative: keep `framework/llm/budget` as the owner. Rejected because Workflow/Harness need the same scope, event, and replay contract without importing provider-specific policy or pricing code.

### 2. Values are typed and immutable; cost is canonical `Decimal`

`BudgetAmounts` exposes six explicit fields rather than an arbitrary dimension map. Count/token values are non-negative bounded integers and reject booleans. Cost is parsed once into finite non-negative `Decimal`, quantized to a fixed precision, and serialized as a canonical decimal string. `BudgetPolicy`, `BudgetScopeRef`, decisions, reservations, settlements, views, events, and snapshots are frozen value objects with strict `from_dict()` unknown-field rejection. A policy may additionally constrain the derived sum `input_tokens + output_tokens + reasoning_tokens` to preserve the existing `max_total_tokens` contract; this is a deterministic constraint over the six facts, not a seventh usage dimension.

Alternative: preserve float and generic mappings. Rejected because float serialization drifts and generic keys would absorb dimensions whose owners and semantics differ.

### 3. One root ledger owns a validated scope tree

A `BudgetLedger` is created with one run scope and root policy. Child scopes are registered explicitly with a parent already present in the same run. A child policy may omit limits or narrow them; it cannot increase any finite ancestor ceiling. Committed and reserved deltas are projected to the operation scope and every ancestor, so independent local views never bypass the root ceiling. Sibling views expose totals and remaining limits only, not reservation payloads or private history.

Alternative: create independent child trackers and periodically reconcile. Rejected because concurrent siblings could each consume the last root slot.

### 4. Reservation is the only admission mutation and is linearized

`preflight()` is a read-only projection. `reserve()` performs policy resolution, ancestor balance checks, idempotency lookup, reservation creation, usage updates, revision increment, and event construction inside one re-entrant lock. An exact repeated `operation_id` plus idempotency key returns the existing reservation. A reused identity with different scope, policy, or requested amounts raises a typed conflict and leaves the ledger unchanged. Denial produces a stable sorted decision and durable fact but no reservation.

The process-local lock is deliberately explicit. A future distributed implementation must satisfy the same port with transactional compare-and-reserve; this change does not claim cross-process atomicity.

### 5. Settlement is terminal, exactly once, and dispatch-aware

An adapter reserves the maximum admitted logical call/input/output/cost amount before external execution. `settle()` validates reservation, operation, scope, policy digest, state, and actual normalized usage. Actual usage replaces reserved input rather than adding it; output/reasoning/cached input/cost are committed once. Exact duplicate settlement delivery returns the stored settlement without changing usage or revision. A conflicting duplicate fails closed.

Known actual usage must fit the reservation ceiling. If it does not, the operation becomes `indeterminate` with its reservation retained until explicit reconciliation; the ledger does not discard known risk or silently exceed policy. This relies on stage-24 output reserve and LLM pricing adapters to reserve conservative ceilings.

An undispatched operation can be released. Once dispatch is confirmed or uncertain, release is forbidden; the adapter must settle actual usage or mark the reservation indeterminate. Stream fragments never settle; only one terminal event does. Each real fallback provider dispatch receives a child attempt operation identity beneath one logical parent.

Alternative: commit usage even when it exceeds the reservation. Rejected because that breaks the invariant that committed plus reserved never exceeds an admitted root ceiling and makes admission non-authoritative.

### 6. `LLMBudgetAdapter` owns translation, not the ledger algorithm

The adapter converts prepared-request counts and output/cost ceilings into `BudgetAmounts`, creates operation identities, and normalizes `TokenUsage`, pricing, cache flags, dispatch state, and terminal outcomes into settlement commands. Cache hits are admitted and settled as one logical call; any observed cache metadata remains an adapter/router observation, while canonical committed physical provider tokens and cost are zero and provider dispatch remains false. Each fallback dispatch is a separate attempt reservation. A lost stream terminal or accepted-but-lost provider response becomes indeterminate.

`GlobalBudgetTracker` remains for one compatibility release as a behavior-free facade around a canonical ledger and adapter. Agent and Workflow modules re-export canonical compatibility types rather than defining models or algorithms. New production paths pass explicit operation/reservation identity.

### 7. Workflow and Agent consume views without losing their own budgets

`WorkflowBudgetTracker` continues to own tool-call and monotonic wall-time usage. Its LLM fields are projected from `BudgetView`; its restore path calls canonical `restore()` or the legacy decoder and never writes private fields. AgentLoop continues to own iteration, parser, judge, output, stall, and retry behavior. It either consumes router settlement metadata or uses the shared adapter for a direct client call, never both.

Subagents receive a registered child scope tied to the root ledger. `inherit_budget=False` may create a separate local projection but never a separate root ceiling.

### 8. Budget events reuse the canonical event runtime

The budget package emits immutable `BudgetEvent` payload projections through a small sink port. The `framework.events` adapter registers and validates `budget_reservation_created`, `budget_reservation_denied`, `budget_reservation_settled`, `budget_reservation_released`, `budget_reservation_expired`, and `budget_reservation_indeterminate` with `newsroom.budget-event/v1`, then creates existing `EventCandidate` records for the configured durable store.

Payloads include run/scope, policy digest, operation/reservation identity, ledger revision, bounded amounts, outcome, and stable reason codes. They exclude prompts, messages, tool payloads, provider bodies, exceptions, credentials, and arbitrary metadata. Failure to durably append an admission mutation fails closed and rolls the in-memory mutation back when the sink declares durable writes required.

Alternative: add a second budget-specific event store. Rejected because stage 19 is the single durable event authority.

### 9. Snapshot, restore, and replay are strict state reconstruction

`BudgetSnapshot/v1` contains the root or selected scope, policy digest, registered policies needed for validation, committed/reserved totals, bounded open reservations, terminal operation records needed for idempotency, last event id, and ledger revision. `restore()` validates schema, digest, scope graph, totals, identities, and invariants before constructing a new ledger; no partially restored ledger is exposed.

Offline replay consumes ordered canonical budget event payloads, requires contiguous ledger revisions, rejects missing/conflicting/unknown/out-of-order facts, and rebuilds the same snapshot. It has no LLM/provider/tool/cache port. Exact storage redelivery of the same event id is rejected as malformed history rather than treated as a new mutation. A read-only decoder maps the legacy flat usage snapshot to a canonical root snapshot with no open reservations; all new writes use v1.

### 10. Harness maps facts to routes, and only Harness

Budget decisions contain `allowed`, sorted reason codes, projected usage, optional reservation id, and revision. They contain no route or executable callback. Router/Agent/Workflow surface the fact to Harness. Harness records the decision and deterministically chooses an allowed bounded transition under its existing state machine. Diagnostics are projections only and cannot mutate the ledger.

## Risks / Trade-offs

- **[Process-local locking does not coordinate multiple hosts]** -> Document the topology limit, expose a ledger port, and do not claim distributed quota until a transactional backend is qualified.
- **[Conservative reservations reduce utilization]** -> Reserve from admitted model limits and pricing ceilings, expose remaining values, and optimize estimates only with conformance evidence.
- **[Legacy callers omit operation identity]** -> The compatibility facade generates bounded identities only for deprecated single-call methods; production router/Agent/Workflow paths must pass explicit identities and architecture tests reject new imports.
- **[Snapshot size grows with idempotency records]** -> Bound open and terminal records, checkpoint only the configured replay window, and fail closed before silently truncating authority-bearing records.
- **[Event append failure can diverge memory and storage]** -> Use prepare/append/commit ordering with rollback for pre-dispatch mutations; post-dispatch uncertainty becomes indeterminate.
- **[Cache accounting changes existing tests]** -> Preserve provider state/cost bypass while explicitly separating logical calls from physical provider dispatch in metadata and specs.
- **[Actual usage exceeds reserved ceiling]** -> Retain reservation, mark indeterminate, and require Harness-controlled reconciliation rather than optimistic release or hidden overage.

## Migration Plan

1. Land U10 parity fixtures and architecture/import inventory before production cutover.
2. Add canonical models, ledger, event payloads, restore/replay, and focused boundary/concurrency tests.
3. Add the LLM adapter and convert `framework.llm.budget.GlobalBudgetTracker` to a canonical facade while preserving one-release read compatibility.
4. Migrate router complete/stream/cache/fallback/error paths to explicit operation identities and terminal settlement.
5. Migrate AgentLoop, subagent, Workflow runner/outcome/checkpoint, and summaries to canonical views and public restore.
6. Register canonical budget event schemas and wire the production event sink; validate redaction and zero-I/O offline replay.
7. Remove duplicate Agent/Workflow implementations and enforce dependency/import boundaries.
8. Run focused suites, architecture, compile, smoke, strict OpenSpec validation, and migration diff checks before commit.

Rollback disables new adapter injection at composition boundaries and decodes the last canonical snapshot into the old read-only flat projection. It must not rewrite canonical history, duplicate already settled provider calls, or release indeterminate reservations. The compatibility facade remains available for one release, but no second mutable implementation is restored.

## Open Questions

- A process-local ledger is the qualified target for this change. Production deployment topology must be reviewed separately before claiming a cross-host quota.
- The exact release number for deleting compatibility exports must be set by release management; the technical expiry is one release after this change ships.
