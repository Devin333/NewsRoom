## Why

The first board workflow stage outcome pass records successful, warning, and failed stages, but a few polish items remain for better diagnostics and compatibility with later runtime verification.

## What Changes

- Add skipped stage and richer recovery action enums.
- Allow stage results to carry lightweight quality, feedback, and guard evidence as serializable dictionaries.
- Add a helper for skipped stage results.
- Record failed-stage duration from the actual current stage start time.
- Clarify the `last_execution` boundary as debug/test convenience.

## Capabilities

### New Capabilities
- `workflow-stage-outcome-polish`: Board workflow stage outcome polish and diagnostics.

## Impact

- Affected code: `business/boards/_workflow_runtime.py`, `business/boards/_workflow.py`, tests.
- Public API impact: additive enum values, additive stage result fields, additive helper.
