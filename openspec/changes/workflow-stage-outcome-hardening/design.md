## Context

Stage outcomes should be additive and must not change board service contracts or hide exceptions.

## Design

- Add `WorkflowStageStatus`, `WorkflowRecoveryAction`, `BoardWorkflowStageResult`, and `BoardWorkflowExecution`.
- `BoardWorkflowBase.run` records each named stage with input/output counts, warnings, errors, duration, and recovery action.
- Exceptions create a failed stage and are re-raised.
- Result metadata includes serialized execution and summary counts.

## Constraints

- Existing `BoardWorkflowTrace` fields remain unchanged.
- No behavior change to board service methods.
