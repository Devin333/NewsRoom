## MODIFIED Requirements

### Requirement: Controlled Failure Outcomes
When VERIFY fails or budgets are exhausted, Harness SHALL choose only explicit controlled outcomes: `replan`, `retry`, `route_to_repair`, `wait_for_approval`, `halted`, or `failed`. A Harness-managed stage MUST be considered safely halted only after its required terminal failure event is durably committed. If that commit fails, Harness MUST fail closed with a typed persistence outcome and MUST NOT report an ordinary `halted`, `blocked`, or business `failed` result.

#### Scenario: Budget exhaustion halts the run
- **WHEN** a Harness run exceeds `max_turns`, `max_replans`, `max_retries_per_step`, or `max_worker_calls`
- **THEN** Harness MUST transition the run to `halted`
- **AND** Harness MUST record the exhausted budget in the run transcript

#### Scenario: TaskPlan halt event cannot be committed
- **WHEN** a TaskPlan stage failure occurs and durable `TASK_PLAN_HALTED` persistence raises an error
- **THEN** Harness MUST return or raise `task_plan_halt_persistence_failed`
- **AND** Harness MUST NOT continue dispatch, aggregation, verification, publication, or report an ordinary terminal stage result

### Requirement: Trace Checkpoint Replay
Harness SHALL record phase transitions, worker calls, gate decisions, budgets, handoffs, RAG refs, memory write intents, artifact publication decisions, and required terminal failure transitions to a durable transcript or event log that can support checkpointing and replay. Gate evidence MUST include the exact gate id and version, deterministic input reference, result reference, pass/fail outcome, stable reason code, aggregate verdict, and resulting scheduler decision before the next state or publication is accepted. Recovery MUST distinguish a durably committed terminal failure from an execution failure whose terminal evidence is absent or uncommitted.

#### Scenario: Replay reads deterministic decisions
- **WHEN** a completed Harness run is replayed from its transcript and checkpoints
- **THEN** the replay reader MUST expose the recorded plan, execution, verify, gate, budget, handoff, and artifact decision events without calling an LLM

#### Scenario: Recovery resumes after committed VERIFY
- **WHEN** VERIFY evidence and its transition were durably committed before a process crash
- **THEN** recovery MUST use the recorded gate evidence and pinned gate version as scheduler input
- **AND** recovery MUST NOT replace the recorded verdict with current defaults or worker self-evaluation

#### Scenario: Recorded gate evidence is incomplete
- **WHEN** recovery cannot resolve the pinned gate version or verify the recorded gate evidence checksum
- **THEN** recovery MUST fail closed with a typed history diagnostic
- **AND** it MUST NOT guess, reclassify the history as passed, or invoke an LLM

#### Scenario: Terminal failure evidence is absent
- **WHEN** recovery observes TaskPlan execution evidence without the required durable `TASK_PLAN_HALTED` transition after a terminal failure
- **THEN** recovery MUST expose a controlled retry, quarantine, or manual-repair state
- **AND** it MUST NOT assume the stage safely halted or continue publication
