## Context

The repository already contains a usable business layer skeleton: foundation primitives/models, layer pipelines, board services, and an interface application service. The PRD package in `docs/business` asks for the final target state where quality learning-loop evidence is native to business objects and board outputs, not a parallel evaluator.

## Goals / Non-Goals

**Goals:**
- Complete target-state contracts under the existing `business/foundation -> business/layers -> business/boards -> interfaces` dependency direction.
- Preserve current tests and runtime entrypoints while adding final-target modules and fields.
- Use deterministic, explainable policy/ranking/quality rules so no real LLM call is required.
- Make all visible board outputs traceable through evidence refs, provenance, quality snapshots, policy snapshots, ranking reasons, and feedback candidates.

**Non-Goals:**
- No `business/evolution`, framework evolution package, web console, real LLM integration, agent swarm, or automatic code/policy activation.
- No rewrite of old daily-intelligence workflow internals unless required for compatibility.
- No concrete storage implementation inside foundation, layers, boards, or interface contracts.

## Decisions

1. **Extend existing foundation models instead of replacing them.**
   The current `business.foundation` API is already consumed by tests and services. New learning-loop objects are added in dedicated modules and exported from foundation to avoid broad breaking changes.

2. **Introduce final-target modules as thin wrappers around existing pipeline capabilities.**
   Existing pipelines remain the executable path. PRD-named modules such as `normalizer.py`, `source_mapper.py`, `quality_checks.py`, `ranking_rules.py`, and presenters delegate to deterministic helpers or existing pipelines.

3. **Keep BoardOutput compatibility and add BoardRunResult.**
   Existing interface tests assert `BoardOutput`; final target requires `BoardRunResult`. Services expose both by wrapping `BoardOutput` with policy snapshots, quality summaries, feedback candidates, trace refs, and manifest refs.

4. **Use policy profile data as ordinary business models.**
   Board policies are versioned `BusinessPolicyProfile` instances, snapshots are fixed per run, candidates stay inactive until regression guard pass plus manual activation.

5. **Cross-board reads processed objects only.**
   Cross-board services operate on relations, cards, radar items, and insights produced by lower layers; they do not collect raw sources or bypass board workflows.

## Risks / Trade-offs

- **Large scope can destabilize existing tests** -> keep edits additive and preserve current public functions.
- **PRD has richer algorithms than a single implementation pass can fully model** -> implement deterministic, explainable rules with complete contracts and tests first.
- **Duplicate concepts already exist in older modules** -> target-state modules become the preferred API; old daily-intelligence code remains compatibility/reference.
- **BoardRunResult may overlap with BoardOutput** -> keep both models and explicitly wrap `BoardOutput` rather than changing existing callers abruptly.
