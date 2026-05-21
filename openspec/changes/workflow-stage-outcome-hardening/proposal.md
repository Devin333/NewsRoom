## Why

Board workflows expose aggregate trace counts but lack stage-level outcomes for failure isolation and recovery diagnostics.

## What Changes

- Add board workflow stage outcome models.
- Record stage results during board workflow execution.
- Add workflow execution metadata to `BoardWorkflowResult`.
- Add tests for normal, warning, and failed stages.

## Capabilities

### New Capabilities
- `workflow-stage-outcome`: Board workflow stage-level outcome and recovery metadata.

### Modified Capabilities

## Impact

- Affected code: `business/boards/_workflow.py`, new workflow runtime models, tests.
- Public API impact: additive metadata and new models.
