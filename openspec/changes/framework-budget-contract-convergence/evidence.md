# Unified Budget Governance Evidence

## 1. U10 parity matrix

The classifications below were established from the live-tree audit. `merge` means cumulative LLM semantics move to the canonical ledger; `retain` means a different domain owner remains authoritative; `adapt` means the path translates domain facts into or consumes canonical lifecycle state. Implementation status and current verification are recorded in Sections 5-8.

| Case | Router evidence | AgentLoop evidence | Workflow evidence | Decision | Canonical owner and reason |
| --- | --- | --- | --- | --- | --- |
| prompt estimate and reservation | `framework/llm/routing/router.py` invokes global preflight/reservation with the admitted component total | `framework/agent/loop/loop.py` independently checks a tracker before direct calls | `WorkflowBudgetTracker` currently has no atomic reservation | `merge` | `framework/governance/budget`; one operation identity and atomic ancestor admission replace check-then-act copies |
| actual usage settlement | Router records normalized `TokenUsage` and cost | AgentLoop records again unless router metadata is detected | Workflow can record the same usage through its own tracker | `merge` | canonical ledger settles exactly once; upper layers consume the same terminal identity |
| reserved prompt replacement | LLM tracker supports `replace_reserved_prompt_tokens` | Agent copy ignores replacement | Workflow copy subtracts a supplied reservation | `merge` | canonical settlement replaces every reserved dimension with normalized actual values |
| per-call provider token/cost policy and pricing | `LLMBudgetPolicy`, estimator, guard, and `ModelPricing` are provider/model-aware | no equivalent owner | Workflow accepts a cost value but does not own provider pricing | `retain` + `adapt` | `framework/llm/budget` retains per-call and pricing; `LLMBudgetAdapter` translates to canonical amounts |
| cache hit | Router cache metadata separates logical request from `provider_call=false` and provider cost | Agent consumes response metadata | Workflow consumes summary | `adapt` | cache remains router-owned; canonical ledger records one logical operation and zero provider cost |
| primary and fallback | Router owns deployment fallback and can dispatch multiple real provider attempts | Agent owns loop-level retry, not provider fallback | Workflow owns step retry, not provider fallback | `retain` + `adapt` | routing remains with router/Harness; each real dispatch gets a distinct child reservation |
| stream terminal | Router accumulates stream usage and currently settles at terminal paths | Agent consumes a final response/result | Workflow consumes final outcome | `adapt` | fragments are observational; only the canonical terminal command settles once |
| provider error and uncertain dispatch | Router has provider error/fallback paths but no shared reservation terminal taxonomy | Agent turns global-budget errors into loop results | Workflow turns results into outcomes | `adapt` | adapter maps proven pre-dispatch failure to release and uncertain/accepted loss to indeterminate; Harness routes |
| checkpoint and resume | LLM tracker exposes only a flat usage snapshot | Agent trace carries projected usage | Workflow resume writes tracker `_usage` directly | `merge` | canonical versioned snapshot/restore/replay replaces private mutation; legacy flat snapshots are read-only inputs |
| cumulative call/token/cost limits | all three modules define `GlobalBudget*` variants | same | same, mixed with legitimate fields | `merge` | only canonical ledger remains mutable |
| tool calls and wall time | not owned | Agent tool policy has separate behavioral limits | `WorkflowBudgetPolicy` and tracker own tool/wall-time | `retain` | Workflow/Agent owners remain separate and only join operator summaries |
| loop iterations, parser/judge, output, stall | not owned | AgentLoop policy/output/stall owners enforce behavior | not owned | `retain` | Agent owner remains authoritative |
| retry credits and deadlines | provider retry and cooldown are distinct | loop retry is behavioral | step retry/deadline is Workflow/Harness-owned | `retain` | existing attempts/Harness owners remain authoritative |
| context window and compaction | stage-24 LLM physical preflight consumes model profile | Agent passes semantic context | Harness owns semantic selection/compaction | `retain` + `adapt` | context owners produce admitted input/output ceilings consumed by the LLM budget adapter |

## 2. Consumer and migration inventory

| Surface | Current consumers | Target |
| --- | --- | --- |
| `framework.llm.budget.GlobalBudget*` | router, Workflow runner, public `framework.llm`, focused tests | one-release facade over canonical ledger plus `LLMBudgetAdapter` |
| `framework.agent.runtime.llm.GlobalBudget*` | AgentLoop, AgentLoop runner, subagent executor, tests/imports | behavior-free re-export only; production consumers import canonical/LLM facade directly |
| `framework.workflow.governance.budget.GlobalBudget*` | Workflow public exports and internal tracker | removed definitions; Workflow consumes canonical view while retaining tool/wall-time state |
| legacy flat snapshot | Workflow summaries/resume and persisted checkpoint payloads | strict read-only decoder to canonical root snapshot; no new legacy writes |
| dynamic/public entry | `framework.llm.__all__`, `framework.workflow.__all__`, runtime dependency injection | compatibility exports documented for one release; new production composition supplies root ledger/scope |

## 3. Golden behavior fixture plan

The conformance fixture will exercise the same operation matrix through canonical ledger, LLM facade, router, Agent direct-call adapter, and Workflow projection. Expected committed/reserved values, sorted violations, cost strings, operation state, and revision are fixed for:

- `None`, zero, `limit-1`, `limit`, and `limit+1` boundaries;
- estimated input replaced by actual input;
- cache hit, primary success, primary failure plus fallback success;
- complete and stream terminal, duplicate terminal, and lost terminal;
- pre-dispatch release, dispatched indeterminate, conflicting identity;
- snapshot, restore, legacy decode, and zero-I/O offline replay.

## 4. Compatibility registry and five-way closure audit

### 4.1 One-release compatibility registry

| Surface | Current owner | Introduced | Expiry | Removal condition | Telemetry / kill switch | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| `framework.llm.budget.GlobalBudgetPolicy`, `GlobalBudgetUsage`, `GlobalBudgetCheck`, `GlobalBudgetTracker`, `GlobalBudgetGuard`, `GlobalBudgetExceededError` | `framework/llm/budget/tracker.py` facade over `BudgetLedger` and `LLMBudgetAdapter` | `0.1.0` | `0.2.0` | remove after downstream imports are migrated and the public compatibility test is deleted | architecture test fails on a second owner; composition can stop injecting the facade while canonical snapshots remain readable | `framework/llm/budget/tracker.py`, `tests/architecture/test_unified_budget_governance.py` |
| Agent runtime budget exports | `framework/agent/runtime/llm.py` explicit re-export | `0.1.0` | `0.2.0` | remove after Agent consumers use `framework.llm.budget` directly | import-boundary test rejects new production imports; no mutable state in the module | `framework/agent/runtime/llm.py`, architecture inventory |
| Workflow governance budget exports | `framework/workflow/governance/budget.py` adapter for Workflow tool/wall-time plus canonical LLM view | `0.1.0` | `0.2.0` | remove cumulative compatibility names after Workflow callers migrate; retain Workflow-owned policy/tracker APIs | adapter injection can be disabled at composition; canonical snapshot/event history is preserved | `framework/workflow/governance/budget.py`, `tests/framework/workflow/test_unified_budget_governance.py` |

The registry is intentionally one release wide. It has no package-external telemetry claim in this repository; the enforceable controls are source inventory, architecture tests, explicit expiry constants, and the composition kill switch.

### 4.2 Required entry-point audit

| Evidence class | Live-tree result |
| --- | --- |
| Production imports | New mutable consumers use `framework/llm/budget` and `framework/governance/budget`; no production import consumes Agent/Workflow compatibility modules for cumulative types. Agent and Workflow exports are compatibility-only. |
| Public exports | `framework.llm` exposes the LLM facade; `framework.agent.runtime.llm` and `framework.workflow.governance.budget` re-export compatibility names without a second ledger. |
| Dynamic entries | Repository search found no dynamic `GlobalBudget*` loader or package entry point. Generic dynamic import helpers remain unrelated registry infrastructure and do not resolve budget symbols. |
| Checkpoint/replay | `framework/workflow/runtime/checkpoint_coordinator.py` writes `canonical_snapshot()`; `framework/workflow/runtime/executor.py` calls the public tracker `restore()` through `restore_global_budget_tracker_usage`; `framework/governance/budget/replay.py` replays only validated budget facts and has no live provider/cache/tool ports. |
| Persisted readers | `framework/workflow/checkpoint/resume.py` carries bounded checkpoint metadata; `budget_usage_from_snapshot()` accepts canonical v1 or the known legacy flat projection; new writes use canonical v1 and never assign `_usage`. |

## 5. Implemented path inventory

| Area | Implemented paths | Contract delivered |
| --- | --- | --- |
| Canonical owner | `framework/governance/budget/{models,ledger,events,replay,errors}.py` | six dimensions, immutable strict models, Decimal cost, scope tree, atomic reservation, terminal idempotency, dispatch-aware release/indeterminate, bounded snapshot and offline replay |
| LLM adapter/facade | `framework/llm/budget/{adapter,tracker,policy}.py` | provider pricing and usage normalization stay at LLM boundary; facade delegates all cumulative mutation to the canonical ledger |
| Router | `framework/llm/routing/router.py` | logical/physical identities, pre-lookup logical cache admission, post-miss physical admission, fallback attempts, stream terminal-only settlement, pre-dispatch release, unknown-dispatch indeterminate |
| Agent/subagent | `framework/agent/loop`, `framework/agent/subagents`, `framework/agent/runtime/llm.py` | direct-client and router paths settle once; child scopes share root capacity; duplicate runtime definitions removed |
| Workflow | `framework/workflow/governance/budget.py`, `framework/workflow/runtime/{runner,executor,checkpoint_coordinator,outcome_finalizer}.py` | tool/wall-time ownership retained; canonical view and public snapshot/restore replace private usage mutation |
| Durable events | `framework/events/{budget.py,schema/catalog.py}`, `framework/harness/control_plane/durable_events.py` | `newsroom.budget-event/v1` lifecycle schemas, bounded redacted durable sink, ordered fact resolver |
| Harness | `framework/harness/control_plane/{cumulative_budget,gates,harness,step_lifecycle,transcript}.py` | durable budget facts feed deterministic VERIFY and bounded HALT/reconciliation; ledger has no route authority |

## 6. Verification ledger

| Gate | Evidence | Status |
| --- | --- | --- |
| strict OpenSpec | `openspec validate framework-budget-contract-convergence --strict` | passed; final rerun follows task/evidence closure |
| canonical unit/contract | `tests/framework/governance/budget -q` | `48 passed` |
| LLM adapter/router | `tests/framework/llm -q` | `194 passed` |
| Agent integration | `tests/framework/agent -q` | `80 passed` |
| Workflow integration | `tests/framework/workflow -q` | `299 passed, 1 skipped` |
| Harness control plane | `tests/framework/harness/control_plane -q` | `559 passed`; final full `tests/framework/harness -q`: `1094 passed` |
| event/transcript/architecture | focused budget/event/Harness/architecture selection | `8 passed`; full `tests/architecture -q`: `112 passed, 4 warnings` |
| focused cross-layer | Agent/Workflow unified tests plus LLM budget tests | `7 passed` |
| compile | `python -m scripts.dev compile` | passed |
| repository smoke | `python -m scripts.dev smoke` | `2064 passed, 23 deselected, 22 warnings`; compile passed; source validation returned `is_valid=true`, `error_count=0`, `warning_count=0` |

The first smoke run exposed a compatibility regression rather than an assertion problem: legacy graph runs without a durable budget fact must omit the opt-in cumulative gate, while fact-bearing runs still evaluate it deterministically. The root cause was fixed, the repaired golden test passes, and the final repository smoke completed successfully.

## 7. Rollback and operational boundary

- Disable new adapter injection at composition boundaries while retaining canonical snapshots and durable facts as the read-only authority. Do not restore a second mutable tracker.
- A legacy flat snapshot is decoded into a canonical root projection only; the next write is canonical v1. Unknown fields, invalid totals, gaps, conflicting identities, and failed durable appends fail closed.
- A known pre-dispatch failure releases reservation; a dispatched or uncertain operation remains indeterminate until Harness-controlled reconciliation. Rollback never releases or replays an indeterminate operation optimistically.
- The ledger lock is process-local. It guarantees thread-level linearization within one process only; cross-host quota requires a future transactional implementation of the same port and is explicitly outside this change.

## 8. Evidence commands and commit closure

The final closure sequence is:

```powershell
openspec validate framework-budget-contract-convergence --strict
python -m scripts.dev compile
python -m scripts.dev smoke
git diff --check
```

The implementation commit is path-scoped to this change and its tests/docs; unrelated user commits and worktree files are not staged.
