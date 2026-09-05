# Implementation Verification

## Status

The change is partially implemented. Checked tasks have focused code and test
evidence; unchecked tasks must not be treated as delivered merely because their
types or entrypoints exist. Generic orchestration remains disabled by default.
This record is not production rollout approval.

The PRD revision `e9a81f7d` expands the contracts. Proposal/design/specs/tasks
now follow G1-G5. The former 16/43 task count is historical, not acceptance of
durable submission/continuation, spawn reconciliation, multi-pool packing or
the expanded golden/replay matrix. No feature flag was enabled by this update.

## Verified Surface

- The Agent-owned orchestration contracts remove the reverse dependency from
  `framework/agent` into Harness while retaining strict request/result parsing.
- Parent delegation covers multi-child candidates, forbidden top-level and child
  control fields, fan-out limits, legacy mapping, bounded joined observations,
  redaction, failed/cancelled/indeterminate/halted outcomes, and turn exhaustion.
- `TaskPlanStageRunner` uses the supervised group/wave coordinator. Focused
  tests prove overlapping child execution, multi-wave join, explicit serial
  fallback, and fail-closed handling when the adapter is unavailable.
- Planning observation tests cover allowlisting, read-only authorization,
  durable receipt integrity, source-ref scope, and replay without live tools.
- Dynamic Research tests retain its fixed roles, aggregation contract,
  claim/quality/publication boundary, static default, and recorded replay path.
- G1 observation limits now use one Agent-owned data contract across AgentLoop,
  Harness and TaskPlanPolicy: 8 tasks, 2048 summary bytes, 16 diagnostics,
  16 refs and `max_observation_bytes=16384`. Old/unknown fields are rejected
  before dispatch; UTF-8 limits and policy checksum roundtrips are tested.
- Windows artifact containment compares equivalent DOS/extended DOS and
  UNC/extended UNC paths without removing their operational long-path prefix.
  Atomic I/O, directory traversal and locks use the corresponding namespace;
  escape/device/reparse defenses and POSIX root semantics are retained.

## Checks

- Combined TaskPlan, AgentLoop, dynamic Research, composition and architecture
  regression: 467 passed, 4 deprecation warnings.
- Agent, tool, and orchestration composition regression, including new parent
  boundary tests: 201 passed, 2 skipped.
- Strict OpenSpec validation: passed.
- PRD-aligned observation/AgentLoop/TaskPlan/composition regression: 155 passed.
- Artifact and transcript boundary regression: 159 passed, 3 skipped.
- Agent and tool regression on the final tree: 202 passed, 2 skipped.
- Earlier required full smoke: 2420 passed, 1 failed due to Windows namespace
  mismatch during concurrent filesystem transcript creation. This was not a
  passed commit gate.
- Repaired-tree required full `python -m scripts.dev smoke`: exit 0. Compile
  passed; Harness/Research/API/service/composition/architecture suite reported
  2475 passed, 23 deselected, 23 deprecation warnings in 842.69 seconds.
- The following offline AgentLoop smoke also succeeded with 3 LLM fixture calls,
  1 tool call and 0 network calls. Evidence manifest:
  `.newsroom/smoke/test-agent-loop-b3bc1b3de37b481c9a288f9035348490/manifest.json`.
- Source validation: `is_valid=true`, 0 errors, 0 warnings.
- Strict OpenSpec validation and `git diff --check`: passed on the updated tree.

These are checks of the current partial implementation, not proof of unchecked
G1-G5 scenarios. No production enablement, external-provider qualification or
rollback rehearsal is claimed. The current checklist has 10/46 completed items.

## Remaining Acceptance Work

- Route generic children through the real controlled Agent runtime and persist
  ToolExecutor/ToolBatchExecutor receipts under their child attempt identity.
- Bind group/wave identity into task-result verification and durable child
  evidence, not only coordinator events.
- Complete bounded planning retries, failure accounting, and crash handling.
- Add durable candidate dedup and RefAuthority, per-task spawn intent/receipt
  reconciliation, multi-pool capacity and versioned budget reservations, and
  terminal dependency blocking under the revised PRD.
- Replace synchronous-only parent dispatch with durable submission and
  idempotent same-turn continuation; complete deterministic summary spill and
  full legacy result/cancellation/recovery golden fixtures.
- Complete negative production composition checks for all required durable
  transcript, artifact, tool, profile and capability dependencies.
- Expand recovery/replay coverage to failed, cancelled, indeterminate,
  lease-expired and serial-fallback groups, with no live execution during replay.
- Capture rollout telemetry and replay evidence before enabling any default or
  presenting the dynamic Research entrypoint as production-ready.
