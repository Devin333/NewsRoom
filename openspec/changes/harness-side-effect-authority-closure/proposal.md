## Why

Harness rejects some top-level worker decision keys, but ambiguous publication, promotion, authorization, and memory-write fields still pass through nested or alternate worker payloads. More importantly, effectful workers can perform writes during `EXECUTE` before deterministic `VERIFY`, and the current Research service can persist failed results into the same latest index used by accepted runs, so the existing authority requirement is not enforced at the actual side-effect boundary.

## What Changes

- Add a Harness-owned side-effect authority contract that separates worker-produced candidates from deterministic authorization and post-VERIFY commit for declared Tool, memory, artifact, and skill handlers; production generic Tool wiring remains with its existing owner.
- **BREAKING**: reject untyped decision-shaped aliases at every supported worker-result ingress; callers that currently use ambiguous keys such as `published`, `promote`, `release`, or nested publication/memory decisions must migrate to explicit observation fields or typed side-effect intents.
- Record the side-effect origin, tenant/subject scope references, pinned gate/policy and approval evidence, authorization decision, idempotency identity, commit outcome, and quarantine disposition through the existing durable Harness transcript/history contract.
- Require failed, halted, cancelled, blocked, or approval-waiting runs to keep candidate and diagnostic outputs outside canonical/published stores and published/latest indexes.
- Make authorized commits idempotent and recovery-safe: the deterministic decision is durable before the effect, the outcome is durable after it, and replay never calls a worker or repeats an already committed effect.
- Add an optional versioned terminal side-effect policy with exact handler, inherited gate/budget evidence, approval or pinned `not_required` evidence, and a persisted bounded retry limit; legacy runs without it remain replay-only compatible.
- Cut the production Research artifact step to post-VERIFY hidden candidate preparation, then let one controller-originated terminal intent atomically publish the prepared artifact group together with trace/transcript before run success becomes durable.
- Preserve failed Research run diagnostics by run id in an isolated disposition, but prevent them from replacing the latest accepted paper run.
- Reconcile the hard-crash window after durable terminal completion but before the accepted Research record is saved, without rerunning workers or effects.
- Harden skill release publication so an ordinary Harness/business run and a worker-supplied promotion-shaped payload cannot mutate the active skill version; only the explicit evaluated, approved, versioned evolution path can publish.
- Keep Tool policy/approval model convergence, event envelope/schema work, Workflow graph semantics, and experience-memory provenance in their existing owning changes.

## Capabilities

### New Capabilities

- `harness-side-effect-authority`: Defines candidate/prepared/quarantine/accepted disposition, authorization, idempotent commit, namespace/index isolation, bounded recovery, and replay rules for Harness-managed side effects.

### Modified Capabilities

- `harness-runtime`: Enforce control-plane authority at worker-result ingress and at the post-VERIFY side-effect commit boundary, with durable replay evidence.
- `harness-skill-evolution`: Require active-skill publication to consume a provenance-bound Harness promotion decision and prohibit ordinary runs or worker candidates from activating a release.
- `research-run-persistence`: Add accepted/quarantine disposition and accepted-only latest semantics while retaining validated by-run diagnostics and version-1 read compatibility. This delta is based on the still-active `research-runtime-production-composition` capability and must archive after that baseline.

## Impact

- Framework: `framework/harness/workers`, `framework/harness/control_plane`, Harness memory/artifact ports, and the existing skill-evolution release boundary.
- Research production adapter: the `publish_artifacts` and terminal diagnostic publication boundaries, Research application service save ordering, durable run-store disposition/latest-index selection, historical failed-manifest visibility, and their recorded transport/restart contracts.
- Tests: adversarial worker-result matrices; failed gate/approval/budget/scope side-effect call counts; decision-before-effect and durable-outcome-before-success ordering; worker- and controller-originated intent identity; recovery/replay idempotency; quarantine/published/latest isolation; ordinary-run skill-promotion count; Research failed-run and accepted-run index behavior.
- Compatibility: existing public Research response fields and run-id reads remain stable; version-1 Research records/indexes are dual-read without byte rewriting, and historical failed records/manifests remain diagnostic-only rather than latest/published. Existing Harness event envelopes and event schema/catalog are reused; additive side-effect refs are coordinated with `durable-event-runtime` through existing decision/history projections. `research-runtime-production-composition` must establish the baseline capability before this change is archived.
