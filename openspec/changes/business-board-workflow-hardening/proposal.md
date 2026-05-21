## Why

The four board workflow modules currently only wrap board service calls, so they do not express the business runtime stages, trace summary, or quality feedback semantics expected from mature board entrypoints.

## What Changes

- Add shared board workflow result and trace models.
- Add a common workflow base that runs explicit board workflow stages while delegating five-layer pipeline execution to board services.
- Upgrade AI News, Project Radar, Paper Radar, and Community Pulse workflow modules to inherit the shared workflow base.
- Preserve existing board service and BoardApplicationService behavior.
- Add tests for workflow execution, trace summaries, policy ids, quality status, no raw payload exposure, and board-specific metadata focus.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `business-board-final-target-runtime`: Four board workflows must expose mature board workflow entrypoints with BoardWorkflowResult and BoardWorkflowTrace summaries.

## Impact

- Affected code: `business/boards/*/workflow.py`, shared board service/workflow helpers, and board workflow tests.
- Public API impact: none; no Web/API endpoint or interface contract change.
- Dependency impact: none; no new external dependencies.
