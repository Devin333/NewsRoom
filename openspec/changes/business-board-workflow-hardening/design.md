## Context

Each board already has a service that executes selection, extraction, relation, analysis, output, board-specific policy, and quality feedback. The workflow modules do not expose that execution semantics; they simply call `build_board_run_result`.

## Goals / Non-Goals

**Goals:**
- Make four board workflows explicit business runtime entrypoints.
- Produce a workflow result containing the existing BoardRunResult plus trace, warnings, and metadata.
- Avoid duplicating five-layer pipeline logic in workflows.
- Preserve existing board service and BoardApplicationService contracts.

**Non-Goals:**
- No cross-board graph/path search.
- No Web/API page or endpoint changes.
- No framework, storage, or worker refactor.
- No scoring or board ranking redesign.

## Decisions

- Add `business/boards/_workflow.py` for shared workflow models and base orchestration.
- Add narrow service hooks to `BoardServiceBase` so workflows can expose stages without copying pipeline implementation.
- Move board-specific enhancement into `apply_board_specific_policy(result)` while keeping `build_board_run_result(...)` compatible.
- Keep workflow metadata/focus board-specific through class attributes, not branching.

## Risks / Trade-offs

- Protected service hooks become workflow dependencies -> keep them internal to `business/boards` and test existing public board service behavior.
- Workflow could drift from service behavior -> have `build_board_run_result(...)` and workflow use the same base result and policy hook.
- Trace counts may become misleading if computed from serialized metadata -> build trace from actual intermediate pipeline objects before policy enhancement.
