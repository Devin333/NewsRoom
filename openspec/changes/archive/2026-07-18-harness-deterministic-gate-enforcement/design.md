## Context

The Harness control plane already owns a bounded `PLAN -> EXECUTE -> VERIFY` state machine, deterministic scheduling, retry/replan budgets, durable transition commits, recorded worker activities, and replay verification. Two live gaps undermine that design:

- `HarnessStepSpec.quality_gate` is serialized but never bound to executable code; `HarnessControlPlane` instead runs one undifferentiated `verify_gates` tuple for every step.
- `_quality_verdict()` accepts step metadata or `worker_result.output["quality_score"]` as a verdict source. `ON_VERDICT` routing can therefore be controlled by a worker observation.

Research exposes the gap because its three workflow specs declare many named gates while the production runtime injects eight broad gates globally. The declaration, implementation, executed result, and durable history do not identify the same contract.

The active `durable-event-runtime` change owns the stored envelope, sequence, transition, decision-history, and replay infrastructure. This change must consume those contracts rather than create a second event or replay path. Existing workflow JSON keeps `quality_gate` as a string, and public Research response envelopes remain stable.

## Goals / Non-Goals

**Goals:**

- Resolve every declared step gate to one deterministic implementation and exact version before any worker call.
- Execute framework mandatory gates plus only the current step's declared domain gate.
- Derive the quality verdict solely from deterministic gate results.
- Persist enough versioned, integrity-protected gate evidence to recover and verify the scheduler decision without consulting a worker or current default.
- Make every Research workflow gate declaration executable or remove the declaration.
- Preserve bounded retries, replans, repairs, approvals, and durable transition ordering.

**Non-Goals:**

- Replacing the Harness scheduler or state machine.
- Changing the StoredEvent envelope, outbox/inbox, stream sequence, checkpoint, or replay engine owned by `durable-event-runtime`.
- Converging the separate Analysis quality engines, Tool authorization policy, Source policy, or RAG-specific session gates in this change.
- Treating AgentLoop output judging, editor rewrite states, or RAG answer/abstention semantics as Harness verdicts when they run outside a Harness step gate.
- Rewriting historical events that predate versioned gate evidence.

## Decisions

### 1. Gate references are versioned strings resolved by a framework registry

`HarnessStepSpec.quality_gate` remains a string for serialization compatibility. A declared gate uses `<gate-id>@<version>`. `DeterministicGateRegistry` owns registrations and returns an immutable binding containing the gate id, exact version, implementation, and declared dependencies.

Before `HarnessControlPlane.initialize()` records `RUN_CREATED`, the registry validates the workflow. It rejects blank or unversioned declared references, unknown versions, duplicate registrations, ambiguous aliases, missing dependencies, and dependency cycles. A rejected workflow produces no worker activity and no successful run projection.

Framework code defines the registry and binding contracts but does not import Research. Research composition registers Research-owned deterministic gate adapters.

Alternatives rejected:

- Using a module-global registry creates hidden mutable state and makes tests and composition order-dependent.
- Resolving a name to the latest version makes recovery dependent on deployment time.
- Adding a second gate list to workflow metadata preserves the current declaration/execution split.

### 2. Mandatory gates and declared quality gates have distinct ownership

Framework mandatory gates continue to enforce structural invariants such as tool allowlists, output schema, deduplication, score range, budget, and skill-evolution budget. They run in stable framework order. The registry then executes only the gate bound to the current step plus its declared deterministic dependencies, de-duplicated by exact gate reference.

`verify_gates` remains the explicit constructor input for mandatory gates so existing test injection stays clear. Domain runtimes must stop passing their complete domain gate suite through that argument and instead compose a registry.

A step with no declared quality gate may still pass framework invariants, but it receives no routable quality verdict. `ON_VERDICT` routing from such a step is rejected during workflow preflight. This preserves framework utility steps without manufacturing a quality decision.

Alternatives rejected:

- Running every registered gate on every step repeats the current broad-suite bug and lets irrelevant gates silently pass.
- Treating absence of a gate as `passed=True` makes an undeclared quality policy indistinguishable from a verified result.

### 3. Gate aggregation is the only Harness verdict constructor

The control plane removes metadata and worker output branches from `_quality_verdict()`. After VERIFY evaluates all required gates, a deterministic aggregator creates `HarnessQualityVerdict`:

- `passed` is true only when every required result passed;
- `score` is the minimum declared gate score when deterministic gates supply scores, otherwise binary `1.0`/`0.0`;
- `issues` and `repair_hints` come only from failed gate results;
- metadata records the aggregation version, declared gate reference, mandatory gate references, input evidence reference, and gate-result reference.

Gate exceptions, missing results, identity mismatches, and non-boolean outcomes become failed deterministic results with stable reason codes. They never default to pass.

`HarnessWorkerResult` continues to carry candidate domain data, diagnostics, and metrics. Verdict-, route-, approval-, memory-, and publication-shaped output remains forbidden. Existing worker self-rating keys migrate to an explicitly observational name and cannot be read by the aggregator or router.

Alternatives rejected:

- Keeping `quality_score` as a fallback preserves worker control over routing.
- Averaging gate scores allows a high score to hide a blocking gate failure.

### 4. Gate evidence uses the existing durable event and history contracts

Every evaluated result is enriched by the control plane with a reserved Harness evidence block containing exact gate id/version, deterministic input checksum, result checksum, and stable reason code. The raw result remains available to the in-process transcript; the safe durable projection keeps non-sensitive identity/pass fields and integrity references according to the existing Harness event schema.

The aggregate verdict and scheduler decision are included in the existing deterministic decision history. VERIFY exit commits a `gate_ref` derived from the canonical durable gate-evidence projection before any completion, repair route, replan, halt, or publication transition is accepted. No new event store or parallel transcript is introduced.

On recovery:

- an incomplete VERIFY with no committed result may re-evaluate only the exact gate version pinned by the run binding;
- a committed VERIFY consumes the recorded gate evidence and aggregate verdict;
- missing evidence, checksum mismatch, unavailable pinned version, or a result count mismatch fails with a typed history error;
- an offline verification replay may re-run the pinned deterministic implementation for comparison, but the comparison cannot replace the recorded scheduler input;
- no recovery or replay path calls an LLM or worker to recreate a verdict.

Historical records without the new evidence remain readable through the existing migration reader but are reported as legacy/unverified; they are not upgraded to verified history by guessing current defaults.

Alternatives rejected:

- Extending the StoredEvent envelope in this change violates stage 19 ownership.
- Re-evaluating the current default gate after a crash can change a historical route.
- Persisting only `passed` loses the implementation and input identity needed for audit.

### 5. Research owns adapters for its declared gates

Research defines deterministic adapters beside the Research workflow/domain contracts. Each of the paper-analysis, paper-RAG, and reader-repair gate references maps to one registered implementation and a committed execution test. Adapters may delegate to existing Research schema, evidence, lineage, namespace, budget, paper-card, reader-payload, or publication rules; they must not duplicate those algorithms inside the framework registry.

Gate declarations that name no real invariant are removed instead of being backed by an always-pass adapter. Broad legacy Research gates injected for every step are retired once the per-step registry is active.

The framework remains domain-neutral and imports neither `business.research` nor concrete infrastructure.

Alternatives rejected:

- Registering no-op gates would make metadata look enforced while preserving the defect.
- Moving Research rules into `framework/harness` would reverse the dependency boundary.

### 6. Existing controlled outcomes and domain variants remain intact

The scheduler continues to select only the existing canonical outcomes and remains bound by `max_turns`, `max_replans`, `max_retries_per_step`, and `max_worker_calls`. A failed gate cannot publish or complete a step. RAG supplemental-round limits remain separate domain limits but still consume the enclosing Harness execution budget.

Editor `pass/rewrite_required/blocked`, RAG `answered/abstained`, citation gates, and standalone AgentLoop output judges retain their domain meanings. They become Harness routing inputs only when an explicit deterministic adapter is declared for a Harness step.

## Risks / Trade-offs

- [Strict preflight exposes many latent Research gate names at once] -> inventory all declarations first, add execution tests per workflow, and never use no-op registrations.
- [Changing worker score semantics alters existing routing tests] -> replace those tests with gate-driven routing fixtures and add a regression proving a high worker score cannot change route.
- [Gate version removal strands recoverable runs] -> keep every version referenced by retained durable history registered until the retention/replay window expires.
- [Gate evidence may contain sensitive details] -> persist checksums and stable reason codes in safe projections; keep raw details under the existing event security policy.
- [Mandatory and declared gates can accidentally execute twice] -> de-duplicate by exact gate reference and test call counts and order.
- [A deterministic gate still reads mutable external state] -> gate inputs must be explicit snapshots or integrity-protected references; network, clock, LLM, and mutable store reads are forbidden during evaluate.
- [Historical history cannot prove a gate version it never recorded] -> keep it readable but explicitly unverified; do not backfill invented evidence.

## Migration Plan

1. Add failing regressions for unknown gates, worker-score routing, per-step gate selection, duplicate/missing registry dependencies, and pinned recovery evidence.
2. Add registry, versioned bindings, result enrichment, and deterministic aggregation behind the existing Harness control-plane boundary.
3. Change scheduler and replay inputs to consume only aggregated deterministic verdicts and canonical gate evidence.
4. Inventory and implement or remove all Research workflow gate declarations, then switch Research composition from a broad `verify_gates` tuple to a Research registry.
5. Migrate worker self-rating output to observational/domain-specific fields and reject verdict-shaped output.
6. Run Harness, durable recovery/replay, Research workflow, architecture, compile, and mandatory smoke gates before cutover.
7. Retain historical readers and pinned gate versions for the declared retention window; remove only superseded broad Research gate wrappers with import and replay evidence.

Rollback reverts the registry binding and Research composition as one code release while preserving all newly committed durable events. It must not restore worker-provided verdicts, skip VERIFY, downgrade the event port, or rewrite gate history. If a registered gate version is faulty, deploy a corrected new version and keep the old version available only for historical verification.

## Open Questions

None for implementation start.
