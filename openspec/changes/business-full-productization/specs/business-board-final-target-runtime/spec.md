## ADDED Requirements

### Requirement: Productized board workflow entrypoints
Each primary board SHALL expose a `build_<board>_workflow()` function returning a WorkflowSpec with the productized board step sequence.

#### Scenario: Productized workflow has required steps
- **WHEN** a caller builds a primary board productized workflow
- **THEN** the WorkflowSpec includes the required thirteen linear productization steps from signal preparation through artifact publishing

### Requirement: Productized board runners
Each primary board SHALL expose a runner class using WorkflowRunner, FunctionStepRegistry, a board artifact publisher, injected dependencies where provided, and deterministic offline defaults.

#### Scenario: Runner executes offline
- **WHEN** a primary board runner runs with raw signal dictionaries and no network or LLM dependency
- **THEN** it completes successfully and returns a RunResult with productized board outputs
