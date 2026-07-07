# rag-worker-planner-wiring Specification

## Purpose
TBD - created by archiving change rag-worker-planner-wiring. Update Purpose after archive.
## Requirements
### Requirement: Worker planner remains candidate-only
Harness RAG SHALL allow worker-generated retrieval plan candidates without allowing workers to make workflow decisions.

#### Scenario: Worker receives bounded planning request
- **WHEN** `WorkerRAGPlanner` is invoked on a round at or after its configured minimum worker round
- **THEN** it SHALL send the worker the session, round index, gap report, executed query history, and forbidden workflow-control fields
- **AND** it SHALL treat the worker output only as a `RetrievalPlanCandidate`

#### Scenario: Deterministic fallback handles unavailable worker
- **WHEN** the worker returns a failed result or no candidate payload
- **THEN** `WorkerRAGPlanner` SHALL return the deterministic fallback plan

#### Scenario: First round can remain deterministic
- **WHEN** `WorkerRAGPlanner` is configured with `min_round_index=1`
- **AND** it is invoked for round 0
- **THEN** it SHALL return the fallback plan without calling the worker

### Requirement: Paper RAG session can opt into worker replanning
Paper RAG sessions SHALL support optional worker-planner wiring while preserving the deterministic default.

#### Scenario: No plan worker keeps deterministic planning
- **WHEN** `PaperRAGSession` is constructed without a plan worker
- **THEN** it SHALL construct `BoundedRAGSessionController` without an explicit worker planner

#### Scenario: Plan worker enables WorkerRAGPlanner
- **WHEN** `PaperRAGSession` is constructed with a Research candidate worker
- **THEN** it SHALL adapt the worker through a Research-owned adapter
- **AND** it SHALL construct `BoundedRAGSessionController` with `WorkerRAGPlanner`
- **AND** the worker planner SHALL start on replan rounds by default
