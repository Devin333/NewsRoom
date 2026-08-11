## MODIFIED Requirements

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
