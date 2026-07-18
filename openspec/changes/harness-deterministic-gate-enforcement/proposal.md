## Why

Harness currently serializes `HarnessStepSpec.quality_gate` without resolving or executing it, while a worker-provided `quality_score` can be converted directly into `HarnessQualityVerdict` and influence `ON_VERDICT` routing. This violates the existing Harness authority contract and makes the durable decision history depend on unbound metadata and worker self-evaluation rather than pinned deterministic gates.

## What Changes

- Add a fail-closed deterministic gate registry that resolves every declared step gate to one stable identity and version before a run starts.
- Execute each step's declared gate together with the framework mandatory gates, then derive the aggregate `HarnessQualityVerdict` only from those deterministic gate results.
- **BREAKING**: worker `quality_score` and worker-supplied verdict-shaped values become observations only and no longer affect verification, routing, retry, replan, repair, halt, memory, approval, or publication decisions.
- **BREAKING**: remove the exported `paper_rag_workflow` and `reader_repair_workflow` metadata-only builders because neither is connected to its production controller; callers must use `PaperRAGSession` and `ReaderRepairService` until a real Harness-controlled workflow is introduced.
- Persist gate identity/version, deterministic input references, individual results, aggregate verdict, and the resulting scheduler decision through the existing durable Harness event contract.
- Pin recovery and replay to recorded gate evidence and gate versions; recovery must not substitute current defaults or rerun an LLM.
- Register or remove every gate name declared by the Research workflows and add committed execution tests for those mappings.
- Preserve the existing bounded `PLAN -> EXECUTE -> VERIFY` state machine, retry/replan budgets, workflow serialization, and public Research result envelopes.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `harness-runtime`: Make declared deterministic gates executable and fail-closed, prevent worker observations from becoming verdicts, and bind durable verification decisions to versioned gate evidence.
- `research-runtime`: Require every Research workflow gate declaration to resolve to and execute through the Harness deterministic gate registry before Research output or artifacts can be accepted.

## Impact

- Affected framework code: `framework/harness/control_plane`, `framework/harness/quality`, `framework/harness/workers`, and `framework/harness/workflow`.
- Affected business code: Research workflow gate declarations and the deterministic Research gate adapters they reference.
- Affected tests: Harness control-plane, routing, durable recovery/replay, workflow serialization, and Research single-paper/reader-repair/RAG workflow tests.
- Existing event envelope, transition ordering, workflow payload shape, retry/replan limits, and external Research API response shapes remain compatible. Historical records keep their recorded gate projections; no event history is rewritten.
