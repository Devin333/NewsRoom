## ADDED Requirements

### Requirement: Board workflow result trace
Each AI News, Project Radar, Paper Radar, and Community Pulse workflow SHALL return a BoardWorkflowResult containing the BoardRunResult, a BoardWorkflowTrace, warnings, and workflow metadata.

#### Scenario: Board workflow emits trace
- **WHEN** a board workflow runs with matching sample input
- **THEN** the result includes BoardRunResult plus trace counts for inputs, selected signals, extraction results, relations, rejected relations, cards, insights, quality status, feedback, and policy profile ids

### Requirement: Board workflow stage semantics
Each board workflow SHALL explicitly express resolve_context, select_signals, run_pipeline, build_board_run_result, apply_board_specific_policy, collect_quality_feedback, and return workflow result stages while delegating five-layer pipeline details to board services.

#### Scenario: Workflow preserves service contracts
- **WHEN** existing board service and BoardApplicationService methods are called
- **THEN** they continue to return their existing BoardOutput and BoardRunResult contracts without requiring workflow callers
