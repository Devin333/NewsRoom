## Context

Stage outcomes are additive metadata for diagnostics. They must not change board workflow outputs, hide exceptions, or alter `BoardWorkflowApplicationService`.

## Design

- Extend workflow status and recovery enums with skipped/retry/fallback/skip values.
- Keep stage evidence fields lightweight and JSON-safe by storing quality checks, feedback events, and guard results as dictionaries.
- Add `skipped_stage_result` for explicit skipped-stage metadata.
- Track current stage name and start time in `BoardWorkflowBase.run`; exception handling uses those values when recording the failed stage.
- Keep `last_execution` for tests/debugging only; successful callers should continue reading `workflow_execution` from result metadata.

## Constraints

- No changes to board service semantics.
- No storage rewrite.
- Existing `BoardWorkflowTrace` fields remain unchanged.
