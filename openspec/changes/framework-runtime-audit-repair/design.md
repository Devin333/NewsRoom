## Context

The audit spans activity execution, dynamic TaskPlan, tool governance, redaction, memory, skill evolution, side-effect recovery, durable events, and test oracles. The common failure mode is not a lack of models or policy fields; it is that an accepted contract is not consumed at the authoritative execution boundary.

Harness remains the control plane. Workers and LLMs may emit candidates and observations, but cannot decide routing, retry eligibility, approval, publication, promotion, or memory mutation. Canonical durable history remains authoritative for recovery and replay.

## Goals / Non-Goals

Goals:

- Make failure, replacement, retry and authorization decisions durable, deterministic and shared across live/recovery/replay paths.
- Preserve data integrity across redaction, references, policy transformations and projections.
- Use production caller evidence to separate immediate release blockers from framework hardening work.

Non-goals:

- Create a second event store, a second scheduler, a global registry, or compatibility shims that conceal the old unsafe path.
- Infer production readiness from fake ports, public exports or test-only adapters.

## Decisions

### 1. Failure results are first-class durable facts

An activity that began execution always yields one typed terminal result. A missing successful candidate is not a reason to discard a timeout/cancellation result. The result must retain attempt identity and termination confirmation so recovery can distinguish retryable failure from indeterminate physical execution.

### 2. TaskPlan uses explicit replacement semantics

`FAILED` is historical state, not automatically an active blocker. A replacement patch creates a new immutable plan version and must carry enough information for projection, aggregation, recovery and replay to agree that the target is replaced. Dependencies must be rewired atomically or rejected at patch validation.

### 3. Policy is executed where authority is exercised

`retryable_reason_codes`, `ToolPolicy.require_approval_for`, MemoryPolicy and approval evidence are execution constraints. They must be read at the runner/executor/mutator, not merely serialized or checked at an earlier convenience layer.

### 4. Remote and candidate metadata are observations, never authority

MCP metadata is untrusted until operator policy classifies it. Candidate metadata cannot stand in for an approval record, evaluation result, promotion decision or memory policy decision. The Harness-owned resolver is the only source of authorization evidence.

### 5. Canonical commit and observation projection are separate outcomes

Once a canonical event append succeeds, a projection sink failure must not recategorize it as a failed durable commit. Projection failure retains its original exception class and becomes observable/retryable without mutating Graph control state.

### 6. P2 work is governed by reachability

Every P2 item includes caller inventory and evidence class. A public framework API with no production caller is still repaired as a contract concern, but its release severity and rollout evidence are not overstated.

## Risks / Trade-offs

- Explicit TaskPlan replacement can require projection/model schema evolution. Retain immutable historic plans and add compatible dual-read/replay logic rather than deleting historical FAILED records.
- Requiring MCP approval by default may increase approval prompts. This is intentional until an operator-owned classification exists.
- Tighter MemoryPolicy checks can reject formerly accepted calls. The rejection is the intended correction; migration needs stable reason codes and scoped tests.
- Indeterminate side effects reduce automatic recovery throughput. The alternative is unverified duplicate external execution.
- Redaction changes may alter future trace hashes. Do not rewrite historic payloads; version vectors and preserve diagnostic comparability.

## Migration Plan

1. Add failure/replacement/policy invariants and adversarial tests before changing runtime behavior.
2. Ship P0 activity terminal behavior with dual-read compatible result/replay handling and monitor old reason codes.
3. Ship TaskPlan replacement/retry/gate changes together; do not independently change only the stage blocked check.
4. Ship Tool/MCP approval and shared redaction behavior behind observable policy metrics, then enable fail-closed defaults.
5. Ship skill/memory policy enforcement with explicit denial diagnostics and no automatic fallback.
6. Resolve P2 items by owner; archive only when reachability evidence, tests and strict validation are recorded.

## Open Questions

- Whether `REPLACED` requires a new `TaskLifecycle` value or an immutable plan-level replacement map projected as `SKIPPED`; decision must preserve checksum/replay compatibility.
- Which operator interface owns an explicit repair action for `termination_confirmed=False` activity and indeterminate serial side effects.
- Whether MCP classifications live in `MCPServerConfig` or an operator-owned per-tool policy registry; the chosen design must be versioned and auditable.
- How historical `TASK_RETRY_SCHEDULED` events whose reason codes would no longer be eligible are surfaced in replay diagnostics without rewriting history.
