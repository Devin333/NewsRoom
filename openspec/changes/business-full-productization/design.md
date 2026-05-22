## Context

The framework runtime already provides workflow execution, standardized results, artifact publishing, trace context, SkillRunner, and quality closure primitives. The business layer has board services and legacy board workflows, but the four primary boards do not yet expose productized WorkflowRunner-based runners, full artifact surfaces, subscription payloads, eval suites, or an approval-gated improvement loop.

The implementation must stay within business/interface/doc/test surfaces and must not move business skill content into framework or change workflow runtime behavior.

## Goals / Non-Goals

**Goals:**
- Productize AI News, Project Radar, Paper Radar, and Community Pulse with independent workflows, runners, artifacts, subscriptions, feedback, improvements, and eval cases.
- Add deterministic, offline business skill wrappers and fallbacks.
- Extend feedback from quality events to learning signals, recommendations, proposals, approval state, overrides, next-run application, and measurement.
- Add additive cross-board and weekly intelligence outputs.
- Preserve existing board service, daily intelligence, weekly intelligence, and interface methods.

**Non-Goals:**
- No framework, agent runtime, Skill Runtime structure, CLI architecture, LangGraph, live network, real LLM, or API-key changes.
- No business workflow migration into framework.
- No automatic source-code mutation from improvement proposals.

## Decisions

- Use function-step `WorkflowSpec`s for productized board workflows. This reuses the existing `WorkflowRunner` and `FunctionStepRegistry` path and keeps all business logic in business modules.
- Keep existing `*Workflow` classes as compatibility wrappers. New `build_<board>_workflow()` functions provide the productized workflow specs without breaking old tests.
- Put repeated board workflow logic in shared business helpers. Board packages only bind board type, service, tags/source types, and exports.
- Wrap framework SkillRunner through `BusinessSkillRuntime`. The wrapper normalizes skill inputs/outputs, captures trace metadata, and falls back deterministically on non-fatal errors.
- Store proposals and learning signals through business-level in-memory and local JSON stores. Approved proposals produce override records; they never edit source code.
- Implement cross-board and weekly enhancements as additive services/artifacts. Existing daily/weekly public APIs and behavior remain valid.

## Risks / Trade-offs

- Broad surface area can create duplicated logic across boards. Mitigation: shared helpers own workflow steps, artifacts, subscription, feedback, and improvement mechanics.
- Skill package schemas may reject mock outputs. Mitigation: deterministic fallbacks match package output schemas and wrapper tests cover failure paths.
- Interface boundary tests forbid direct workflow-runtime internals in interfaces. Mitigation: `BoardApplicationService` imports board runners/services only and returns `RunResult` without touching executor internals.
- Local JSON stores can create persistent state during tests. Mitigation: in-memory defaults and tmp-path tests for local stores.

## Migration Plan

- Add OpenSpec artifacts, validate strict.
- Add foundation skill/subscription/feedback/evaluation modules with tests.
- Add shared board productization helpers and wire four board packages.
- Extend BoardApplicationService with productized entrypoints.
- Add cross-board and weekly additive services/artifacts.
- Run targeted tests first, then the full requested acceptance commands.
