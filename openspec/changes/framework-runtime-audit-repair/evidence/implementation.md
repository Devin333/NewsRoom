# Framework Runtime Audit Repair Evidence

## 1. Baseline and Scope

- Repository: `F:\github\Agora-Hub`
- Baseline `HEAD`: `41f5c1f5b1b8954eb05e5db6bde8b721bb140078`
- Baseline branch: `main`
- Baseline date: `2026-09-03` (Asia/Shanghai)
- Active OpenSpec changes: `framework-runtime-audit-repair`, `harness-runtime-execution-safety`
- The worktree already contained active audit-repair changes and unrelated user changes. No reset, checkout, or broad cleanup was performed. Final staging is path-scoped.

The implementation scope is the PRD P0/P1 set `R0-ACTIVITY-TERMINAL` through
`R6-MEMORY-POLICY`. P2 items remain explicitly classified below; no production
readiness or deployment evidence is inferred from in-memory test ports.

## 2. P0/P1 Implementation Matrix

| Finding | Implementation evidence | Regression evidence | Status |
| --- | --- | --- | --- |
| `R0-ACTIVITY-TERMINAL` | `framework/shared/attempts.py` distinguishes deadline, cooperative cancellation, and unconfirmed termination. `framework/harness/runtime/activity_executor.py` wraps every started non-success worker outcome with typed terminal evidence. `framework/harness/runtime/graph_dispatcher.py` preserves terminal evidence, quarantines unconfirmed termination, and consults durable recovery before redispatch. `framework/harness/control_plane/graph_application.py` records physical ownership before dispatch. Production composition passes `event_port.recover_graph` from `interfaces/composition/agent_loop_graph.py`, `backend/research/application/single_paper_runtime.py`, and `backend/research/application/reader_repair_runtime.py`. | `pytest tests\\framework\\harness\\runtime\\test_graph_physical_activity_executor.py -q` -> `19 passed`; `pytest tests\\framework\\harness\\control_plane tests\\framework\\harness\\runtime -q` -> `364 passed`; research application/integration/interface composition suites -> `19 + 20 + 50 passed`. | Implemented; inherited restart/deployment qualification remains blocked. |
| `R1-TASK-REPLACEMENT` | `framework/harness/task_plan/patches.py`, `store.py`, and `durable_store.py` project replacement explicitly and reject invalid target states. `stage.py` excludes replaced historical failures from blocked detection. `replay.py` verifies parent plan, role preservation, dependency/input rewiring, and replacement checksums. | `pytest tests\\framework\\harness\\task_plan -q` -> `108 passed`, including runner-level replacement, durable replay, and recovery cases. | Implemented. |
| `R2-TASK-RETRY` | `stage.py` checks `retryable_reason_codes`, max attempts, and crash-window recovery. `replay.py` validates retry reason and failed-result checksum. Empty retryable-code lists are treated as non-retryable. | Included in the TaskPlan suite: `108 passed`; gate-failure and transport-retry matrix assertions are present in `tests/framework/harness/task_plan/test_task_plan_runtime.py`. | Implemented. |
| `R3-TOOL-APPROVAL` | `ToolExecutor` calls `ToolPolicy.requires_approval`. `framework/tool/runtime/mcp_adapter.py` treats missing or invalid remote risk metadata as dangerous and approval-required. Remote metadata remains observation-only. | `pytest tests\\framework\\tool -q` (within the combined policy suite) passed; `tests/framework/tool/runtime/test_mcp_result_persistence.py` covers missing metadata and no remote invocation. | Implemented. |
| `R4-REDACTION-INTEGRITY` | `framework/shared/redaction.py` and `framework/llm/redaction/redactor.py` use bounded secret patterns and typed field handling. Non-secret domain text and numeric fields are preserved. | Combined Tool/LLM/shared suite -> `144 passed, 2 skipped`; redaction positive/negative and transcript assertions are in `tests/framework/shared/test_redaction.py` and `tests/framework/llm/test_clients_cache_prompt_redaction.py`. | Implemented. |
| `R5-SKILL-APPROVAL` | `framework/harness/skills/evolution/gates.py` no longer accepts candidate-owned approval evidence. `promotion.py` resolves real approval/evaluation records and fails closed when held-out evaluation is unavailable. | Skill evolution assertions are included in the combined policy suite -> `144 passed, 2 skipped`. | Implemented as a framework contract; no production skill-promotion caller is claimed. |
| `R6-MEMORY-POLICY` | `MemoryRuntime.write`, `promote`, `invalidate`, `invalidate_many`, and `forget` use runtime-owned policy decisions and operation traces. Promotion and write transformations revalidate target scope/kind. Caller-supplied policy cannot broaden direct mutation authority. | `pytest tests\\framework\\memory -q` -> `34 passed`; `tests/framework/memory/runtime/test_memory_policy_mutations.py` covers global denial, policy override denial, transformed target validation, invalidate, and forget traces. | Implemented as a public runtime contract; current Research production caller inventory has no direct mutation wiring. |

## 3. Caller Inventory

### Production Graph roots

The physical Graph dispatcher is reachable from these composition roots:

- `interfaces/composition/agent_loop_graph.py`
- `backend/research/application/single_paper_runtime.py`
- `backend/research/application/reader_repair_runtime.py`

All three bind `durable_recovery_resolver=event_port.recover_graph`. The
`HarnessControlPlane` wrapper delegates `reconcile` through its dispatch queue,
so a durable `GRAPH_WORKER_CALLED` marker without a result cannot silently turn
into a second physical invocation after restart.

### Public framework APIs without current Research production callers

The following remain contract-level surfaces in this change and are not
described as online incidents without a caller:

- direct `MemoryRuntime.promote`/`invalidate`/`forget` mutation APIs;
- skill-evolution candidate/evaluation/promotion fake ports;
- TaskPlan direct in-memory and durable store patch APIs;
- side-effect recovery fixtures and in-memory event ports.

The absence of a current caller lowers rollout severity; it does not remove the
policy and replay invariants from the public contract tests.

## 4. P2 Disposition

| P2 item | Evidence class | Owner change | Trigger and disposition |
| --- | --- | --- | --- |
| `P2-TASK` gate registry and retry-result semantics | `contract_reproduced` | `framework-runtime-audit-repair` | Closed in this change through real gate-ref preflight and aligned in-memory/durable result selection. |
| `P2-SIDE-EFFECT` serial crash window | `runtime_reproduced` | `harness-side-effect-authority-closure` | Deferred. Trigger is a production serial external handler. Requires capability-backed reconcile or explicit indeterminate quarantine. |
| `P2-LIFECYCLE` queue lease, child cancel/join, wait binding retention | `coverage_gap` | `harness-runtime-lifecycle-hardening` | Deferred until the affected executable-node, queue, child, or wait-binding composition is production-enabled. |
| `P2-LLM` deadline/cancel propagation and system-preserving compression | `coverage_gap` | `llm-openai-compatible-runtime-hardening` | Deferred until an OpenAI-compatible production composition requires `AttemptContext` propagation. |
| `P2-STORAGE` artifact checksum and skill path containment | `coverage_gap` | `artifact-skill-integrity-hardening` | Deferred until resolver/replay or skill package loading is connected to production storage. |
| `P2-EVENT` canonical append versus projection sink and corruption class | `contract_reproduced` | inherited `durable-event-runtime` | Canonical event/projection contract is retained; deployment observation and rollback qualification remain external gates. |
| `P2-TEST-ORACLE` exact runtime/caller oracles | `coverage_gap` | `framework-runtime-test-oracle-hardening` | Deferred as a separate owner change. This change adds behavior-level negative assertions for P0/P1 paths. |
| `P2-EVAL` real held-out evaluation records | `contract_reproduced` | `artifact-skill-integrity-hardening` | Framework promotion remains blocked without real cases; no default score or production approval is claimed. |

## 5. Verification

Completed focused checks in this worktree:

```text
.\.venv\Scripts\python.exe -m pytest tests\framework\harness\runtime\test_graph_physical_activity_executor.py -q
19 passed

.\.venv\Scripts\python.exe -m pytest tests\framework\harness\task_plan -q
108 passed

.\.venv\Scripts\python.exe -m pytest tests\framework\harness\control_plane tests\framework\harness\runtime -q
364 passed

.\.venv\Scripts\python.exe -m pytest tests\framework\tool tests\framework\llm\test_clients_cache_prompt_redaction.py tests\framework\shared\test_redaction.py tests\framework\harness\skills\evolution tests\framework\memory -q
144 passed, 2 skipped

.\.venv\Scripts\python.exe -m pytest tests\backend\research\application\test_analyze_paper_use_case.py tests\backend\research\application\test_reader_repair_runtime.py -q
19 passed

.\.venv\Scripts\python.exe -m pytest tests\backend\research\integration\test_single_paper_loop_fake_runtime.py tests\backend\research\integration\test_reader_repair_rag_loop.py -q
20 passed

.\.venv\Scripts\python.exe -m pytest tests\interfaces\composition\test_research_recorded_transport.py tests\interfaces\services\test_agent_loop_graph_service.py tests\interfaces\services\test_research_service.py tests\interfaces\services\test_reader_repair_factory.py -q
50 passed, 5 warnings

git diff --check
passed
```

The two skipped policy-suite cases require symlink/junction creation, which is
not permitted by this host. The warnings are existing FastAPI/httpx lifecycle
deprecations and do not change the assertions.

## 6. Release Qualification Blockers

`python -m scripts.dev compile` passed during the implementation checks. The
required `python -m scripts.dev smoke` wrapper was run with the project
`.venv` and a 604-second bounded wall-clock window on `2026-09-03`; it did not
return before the bound and exited with timeout code `124`. A prior bounded run
also reported the pytest pipe-close `OSError: [Errno 22]` while the terminating
tool stopped the process. No full-wrapper smoke pass is claimed. Independent
portions completed before termination, including source validation and the
agent-loop smoke; the smoke process tree was explicitly confirmed stopped.

The remaining release gates are inherited and external to this implementation:

- `harness-runtime-execution-safety` tasks `5.1`-`5.4`: process-restart tests
  against a real Docker/provider, production caller scan, deployment capability
  matrix, observation and rollback evidence;
- real production deployment observation and governance signatures;
- the full smoke wrapper, whose timeout is recorded above;
- five out-of-scope structured-output release tests currently fail because the
  existing provider schema corpus `content_digest` does not match its content.
  Those tests and their evaluation/config files are outside this change and
  were not rewritten as part of the runtime repair.

These blockers keep `tasks.md` item `2.5` and release item `6.2` unchecked. They
do not invalidate the focused P0/P1 behavior evidence above.

## 7. Path-Scoped Commit Boundary

Only the implementation files, regression tests, `tasks.md`, and this evidence
file belong to this change. Existing unrelated worktree edits are preserved;
the final commit must use an explicit path list (including a forced add for the
ignored OpenSpec evidence path). The final commit hash is available from
`git log` after that scoped commit; no unrelated file is reset or included by
this evidence.
