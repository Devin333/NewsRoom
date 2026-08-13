## Why

Production Research dynamic TaskPlan currently constructs `SubAgentRuntime` without a durable transcript store, so transcript refs point to process-local fake state and cannot survive restart, support authoritative replay, or prove that a task result was accepted against readable child evidence. The gate only checks that a ref string is non-empty, while TaskPlan result/event records omit the transcript identity and checksum entirely.

## What Changes

- **BREAKING** Require every `SubAgentRuntime` construction to explicitly provide a transcript store; production composition must provide a durable adapter and tests must explicitly opt into the fake store.
- Upgrade `SubAgentTranscript` to a versioned, immutable, checksum-bound document tied to parent/child/workflow/stage/task/attempt identity, with bounded allowlisted evidence refs and stable failure facts.
- Introduce a typed `SubAgentTranscriptReceipt` plus `write`, `read`, `verify`, and bounded parent-query port semantics with idempotent same-body writes and fail-closed conflicts.
- Add a production filesystem-backed Harness transcript adapter with one run-scoped immutable attempt bundle per invocation, restart-safe reads, identity/path/checksum validation, tamper detection, and bounded payload enforcement.
- Replace the truthy-ref transcript gate with receipt/read-back verification before TaskPlan result acceptance.
- Extend `SubAgentResult`, `TaskResultRecord`, TaskPlan result events, replay, checkpoint, and recovery paths with typed transcript evidence for subagent attempts.
- Close output/result ref ownership so accepted subagent results only reference durable, resolvable candidate output documents rather than synthetic URI strings.
- Record stable, sanitized transcript persistence and verification diagnostics without exposing raw prompts, sibling context, secrets, or unbounded worker output.

## Capabilities

### New Capabilities

None. Durable subagent transcript is part of existing Harness subagent isolation, TaskPlan result integrity, and replay authority rather than a parallel capability.

### Modified Capabilities

- `harness-runtime`: Strengthen subagent isolation and trace/replay requirements so production subagent attempts have readable checksum-bound transcripts and persistence failures fail closed before control transitions.
- `harness-task-plan`: Require subagent task results and lifecycle events to carry verified transcript evidence, and require replay/recovery to resolve that evidence without live workers.

## Impact

- Affected framework code: `framework/harness/subagents/**`, `framework/harness/task_plan/**`.
- New production adapter ownership: `infrastructure/storage/harness/**`.
- Production wiring: `interfaces/composition/research.py` and Research production composition validation.
- Contract and migration impact: existing process-local transcript refs remain diagnostic-only legacy evidence and cannot be treated as readable durable history; new TaskPlan result readers must support the prior schema without manufacturing transcript evidence.
- Test impact: SubAgent runtime/gate contracts, durable adapter restart/concurrency/tamper tests, TaskPlan result/event/replay/recovery tests, Research dynamic analysis integration, architecture checks, and mandatory smoke.
