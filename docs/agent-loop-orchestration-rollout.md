# AgentLoop Orchestration Rollout

## Scope

The generic `delegate_batch` orchestration port is disabled by default. The
application composition layer owns the immutable `AgentLoopOrchestrationFeature`
decision; workers and AgentLoop actions cannot enable it at runtime.

The intended first business rollout target is the opt-in dynamic Research workflow,
after controlled generic AgentLoop acceptance.
The feature value currently controls the AgentLoop composition binding; it is
not evidence that a production Research entrypoint has enabled the complete
child tool/receipt path. Production rollout remains pending the unchecked
tasks in `harness-codex-style-parallel-agent-orchestration`.

The composition policy supports these selections:

- `enabled=True, rollout_scope="research_dynamic"` enables the port for the
  AgentLoop binding when composed with the `research_dynamic` scope.
- The generic AgentLoop scope remains disabled until a separate rollout decision
  is made.
- With the feature disabled or unavailable, the legacy single-child path remains
  active and no ad hoc executor is installed.

## Production prerequisites

Composition must fail closed unless all of the following are present and bound
to the same stage policy:

- a `PlanCandidateBuilderPort` implementation;
- a `ParallelAgentCoordinator` with `ChildAgentSupervisor` lifecycle authority;
- an explicit `SerialTaskExecutorPort` only when the policy enables
  `serial_fallback`;
- pinned active worker bindings and worker contracts for every allowed
  capability;
- a durable `DurableTaskPlanStore`, checkpoint store, and subagent transcript
  store;
- a `TaskPlanResultVerifierPort` with an artifact-reference verifier;
- a Harness-owned planning observation port when planning tools are granted;
- task profiles whose output roles, schemas, and deterministic gate references
  match the policy.

Capacity exhaustion is not an implicit serial fallback signal. Under the revised
PRD, capacity waiting keeps tasks durably READY and may return a bounded PENDING
submission receipt without advancing parent reasoning. Deadline exhaustion or
unavailable required dependencies follow the pinned failure policy. Durable
submission/continuation and multi-pool admission remain pending implementation.

## Independent acceptance gates

- G1: contracts, candidate dedup, reference authority, budgets, events and history.
- G2: overlap, multi-pool packing, dependency closure and spawn reconciliation.
- G3: real generic composition, durable parent continuation and legacy fixtures.
- G4: Research field-level golden parity, static default and publication gates.
- G5: controlled enablement, telemetry/alerts, recovery and rollback rehearsal.

The feature selection API alone does not satisfy any production acceptance gate.

## Telemetry and replay evidence

Before expanding rollout, retain durable evidence for representative runs:

- requested and effective parallelism, wave count, and child lifecycle states;
- dispatch, retry, replan, recovery, cancellation, and degraded-reason events;
- planning tool receipts with request checksums and budget consumption;
- checkpoint and transcript checksums sufficient for offline replay;
- replay results proving no live worker or tool invocation occurs during replay.

The evidence must show that completion order does not affect deterministic join
order and that every VERIFY decision came from a deterministic gate.

## Rollback

Rollback is a composition/configuration change for new requests: disable the
feature, remove the rollout selection, or select a policy-approved explicit
serial adapter. Active groups retain their original pinned join policy, budget,
bindings and history while they recover, cancel or halt. Online recovery permits
only audited status/reconcile and safe policy-authorized new attempts; offline
replay never calls live dependencies. Do not disable quality gates, authorization
checks, or transcript/artifact verification to force a run through.

Serial fallback requires an explicit adapter and policy opt-in and cannot bypass
required durable dependencies, resource conflicts or attempt receipts. Rollback
evidence must retain affected run/stage/capability identities, last accepted plan
versions, unsettled reservations and reasons; inspection and replay remain usable.
