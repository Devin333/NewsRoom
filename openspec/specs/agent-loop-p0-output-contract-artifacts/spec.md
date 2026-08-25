# agent-loop-p0-output-contract-artifacts Specification

## Purpose
TBD - created by archiving change agent-loop-p0-output-contract-artifacts. Update Purpose after archive.
## Requirements
### Requirement: AgentLoop OutputJudge validates JSON Schema contracts
AgentLoop SHALL validate final outputs through the canonical compiled structured-output contract before rule, policy, domain, and evidence checks. OutputJudge SHALL return bounded stable diagnostics; Harness SHALL own retry, replan, accept, and halt dispositions under the configured iteration and retry budgets, and SHALL record every structured-output attempt disposition in replayable events.

#### Scenario: Final output violates the managed contract
- **WHEN** an agent returns `final_output` that fails JSON decoding, canonical schema validation, or typed validation
- **THEN** OutputJudge returns a retry verdict with capped `StructuredOutputDiagnostic` values and no raw rejected output
- **AND** AgentLoop records the attempt fingerprint, contract identity, remaining budget disposition, and repair request
- **AND** the client transport layer does not retry the schema failure

#### Scenario: Rejected output repeats without change
- **WHEN** the next agent attempt produces the same rejected response fingerprint and diagnostic identity
- **THEN** Harness deterministically halts the repair path through the existing retry-exhausted state without another unchanged worker attempt

#### Scenario: Repair budget is exhausted
- **WHEN** a structured-output retry would exceed the configured judge retry or iteration budget
- **THEN** AgentLoop records a budget-exhausted disposition and returns a deterministic non-success terminal result

#### Scenario: Final output satisfies schema constraints
- **WHEN** an agent returns `final_output` that matches the managed contract
- **THEN** OutputJudge continues to evaluate rule, policy, domain, and evidence boundaries before accepting
- **AND** schema acceptance alone does not authorize cache publication, artifact publication, or workflow success

### Requirement: Writer and Editor agents preserve evidence boundaries
AgentLoop SHALL keep WriterAgent and EditorAgent constrained to provided
evidence and restricted tools.

#### Scenario: Restricted writing agent asks to fetch
- **WHEN** a WriterAgent or EditorAgent requests a live fetch tool even if the
  agent spec allowed it
- **THEN** the resolved tool policy hides or blocks the fetch and the tool is
  not executed

#### Scenario: Edited output adds a new cited fact
- **WHEN** an EditorAgent final output cites known evidence but adds a factual
  claim not supported by that evidence
- **THEN** OutputJudge returns a retry verdict with quality error diagnostics

### Requirement: Graph activity captures AgentLoop LLM call artifacts

Graph AgentLoop activities SHALL persist redacted LLM call request/response artifacts through the artifact-owned port and include checksum-bound refs in the node outcome and Graph run manifest. `AgentLoop` SHALL not publish artifacts or decide manifest acceptance.

#### Scenario: Graph AgentLoop activity completes with LLM calls

- **WHEN** a Graph AgentLoop activity produces one or more LLM calls
- **THEN** the artifact owner writes redacted LLM call JSON with checksum, size, type, Graph run id and node-instance metadata
- **AND** Harness records the refs only after deterministic artifact and output gates pass

#### Scenario: AgentLoop attempts direct publication

- **WHEN** AgentLoop returns a candidate that includes an unverified artifact path or publication instruction
- **THEN** Harness treats it as candidate data and does not add it to the Graph manifest

### Requirement: Admission and execution outcomes are stable and scope-aware
The runtime SHALL emit separate durable admission and execution outcomes with stable reason codes, redacted policy/deadline calculations, local/root budget snapshots, operation identity, and determinacy/termination fields. Admission rejection events SHALL omit `attempt_id` and `local_attempt_no`; started attempt events SHALL include them. New live events SHALL NOT emit generic attempt `fencing_token` fields.

`AttemptSupervisor` SHALL be the sole publisher of the three generic lifecycle facts. A lifecycle sink explicitly attached to an outer operation SHALL be inherited by nested Tool, MCP, ToolBatch, parallel branch, and Worker operations without duplicate delivery to the same sink object. Durable sinks SHALL be required and fail closed; explicitly soft Tool/telemetry sinks SHALL be failure-isolated. A required started-sink partial failure SHALL close any previously recorded start with a terminal failure before the unopened callable is discarded.

#### Scenario: Rejection event distinguishes no-start from timeout
- **WHEN** deadline, local budget, root credit, capacity, or parent cancellation rejects a request
- **THEN** the event uses the corresponding `attempt_*` reason code, records `started=false` and no attempt identity, and does not classify the result as a post-start timeout

#### Scenario: Started outcome carries determinacy
- **WHEN** a physical attempt succeeds, fails, confirms timeout termination, or remains unconfirmed
- **THEN** its outcome records `attempt_id`, local attempt number, stable operation key, termination confirmation, and `SUCCEEDED`, `FAILED`, `TIMED_OUT`, or `INDETERMINATE` state consistently

#### Scenario: Soft telemetry cannot gate execution
- **WHEN** a Tool event mirror or Worker telemetry sink fails while a required durable sink remains available
- **THEN** the callable and required lifecycle continue, while the soft sink failure changes neither admission nor the terminal result

### Requirement: Legacy attempt history is read-only replayable and new history is unambiguous
The runtime SHALL provide a versioned read-only decoder for legacy shared-budget and `fencing_token` event/error fields. Legacy `max_total_attempts` SHALL NOT be silently mapped to `max_total_retries`; migration or compilation SHALL explicitly produce the new policy. Offline replay SHALL not invoke workers, Tools, transports, leases, or external effects, and new live history SHALL use scope-aware identity without generic attempt fences.

#### Scenario: Legacy replay has no live side effect
- **WHEN** an old history containing shared permit and fencing fields is replayed
- **THEN** the decoder exposes legacy fields for diagnostics only, replay produces the same projection without starting live work, and no new resource lease is accepted from the old value

#### Scenario: New history contains no generic fence
- **WHEN** a new execution emits admission and attempt events
- **THEN** the serialized records contain local/root budget and resource-specific lease fields where applicable but no generic attempt `fencing_token` field
