## Why

NewsRoom currently has three mutable implementations of cumulative LLM call, token, and cost accounting across the LLM router, Agent runtime, and Workflow governance. Their preflight, reservation, settlement, cache, concurrency, and restore semantics diverge, so the same operation can be double-counted, concurrent callers can exceed a shared ceiling, and recovery can mutate private tracker state instead of replaying a durable public contract.

This change establishes one framework-level cumulative LLM budget ledger while preserving the existing ownership of per-call provider limits, context capacity, AgentLoop behavior limits, Workflow tool/wall-time limits, retry credits, and Harness routing decisions.

## What Changes

- Add an immutable, versioned canonical budget contract under `framework/governance/budget` for six cumulative LLM dimensions, explicit run/workflow/agent/subagent scopes, atomic reservation, exactly-once settlement, read-only views, snapshots, and stable diagnostics.
- Add durable budget lifecycle facts and fail-closed offline replay for created, denied, settled, released/expired, and indeterminate operations.
- Add an LLM-owned adapter that translates prepared-request estimates, normalized provider usage, pricing, cache, fallback, stream, and dispatch metadata into the canonical lifecycle without moving per-call policy or pricing ownership.
- Migrate router, AgentLoop, subagent, Workflow runner/outcome/checkpoint, and production composition to share operation identity and canonical views instead of maintaining independent cumulative trackers.
- Preserve Workflow tool/wall-time accounting, Agent loop/output/stall accounting, retry/deadline accounting, and context admission in their current domain owners.
- Revise cache-hit accounting so a cache hit remains one canonical logical LLM operation while provider dispatch and provider cost remain zero.
- Make budget exhaustion a typed deterministic observation recorded durably for Harness; only Harness selects retry, replan, approval, halt, failure, or publication routes.
- **BREAKING**: new production code may no longer define or instantiate cumulative `GlobalBudget*` implementations from Agent or Workflow modules; temporary compatibility exports delegate to the canonical ledger and have an explicit removal window.

## Capabilities

### New Capabilities

- `cumulative-llm-budget`: Canonical dimensions, policy, scope inheritance, atomic admission, read-only views, and deterministic limit decisions.
- `llm-budget-operation-lifecycle`: Idempotent reservation, dispatch-aware settlement/release/indeterminate semantics, normalized accounting, and adapter conformance across router, AgentLoop, Workflow, cache, fallback, and stream paths.
- `llm-budget-durable-replay`: Versioned safe snapshots, canonical lifecycle events, restore, and zero-provider-call offline replay.

### Modified Capabilities

- `llm-router-cache-integration`: Cache hits participate in canonical logical-operation admission and settlement while continuing to bypass provider cooldown, dispatch, token/cost charging, and provider state mutation.
- `harness-runtime`: Canonical budget decisions and lifecycle facts become durable deterministic inputs to Harness-controlled bounded routing; the ledger never chooses a workflow transition.

## Impact

- New framework owner: `framework/governance/budget`.
- Migrated framework surfaces: `framework/llm/budget`, `framework/llm/routing/router.py`, `framework/agent/runtime/llm.py`, `framework/agent/loop`, `framework/agent/subagents`, `framework/workflow/governance/budget.py`, Workflow runtime/checkpoint integration, and canonical event/replay adapters.
- Public compatibility surfaces under `framework.llm`, `framework.agent.runtime.llm`, and `framework.workflow` become stateless aliases or adapters during one release and no longer own ledger state or serialization.
- Existing persisted flat budget snapshots remain read-only migration inputs; new writes use the versioned canonical schema.
- Tests gain parity, boundary, concurrency, idempotency, cache/fallback/stream, crash recovery, replay, redaction, and dependency-direction coverage.
