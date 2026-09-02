## ADDED Requirements

### Requirement: Canonical Lab workflow state
Projects Lab SHALL expose a canonical current_stage and next_action for every session response.

#### Scenario: New session is clarifying
- **WHEN** a valid Lab session is started
- **THEN** current_stage is clarifying_requirements
- **AND** next_action is answer_question
- **AND** can_generate_solution is false
- **AND** unanswered_question_ids contains every returned question id

#### Scenario: All questions are answered
- **WHEN** the last unanswered Lab question receives a valid non-empty answer
- **THEN** current_stage is ready_to_generate
- **AND** next_action is generate_solution
- **AND** can_generate_solution is true
- **AND** unanswered_question_ids is empty

#### Scenario: Solution is generated
- **WHEN** generate-solution passes the readiness gate
- **THEN** current_stage is solution_generated
- **AND** next_action is review_solution
- **AND** can_generate_solution is false

### Requirement: Server-owned generation gate
The Lab service SHALL decide whether a solution can be generated and SHALL reject premature generation.

#### Scenario: Generate before all required questions are answered
- **WHEN** generate-solution is requested while can_generate_solution is false
- **THEN** the service SHALL NOT execute solution generation
- **AND** the API SHALL return HTTP 409
- **AND** the error code SHALL be lab_session_not_ready
- **AND** the error detail SHALL include unanswered_question_ids

#### Scenario: Client sends stale readiness
- **WHEN** the client sends a request after another answer changed the session
- **THEN** the service SHALL reload the durable session
- **AND** SHALL recompute readiness before generating

### Requirement: Deterministic answer transition
Answering a Lab question SHALL be validated and SHALL preserve unrelated session data.

#### Scenario: Valid answer
- **WHEN** an existing question receives a non-empty trimmed answer
- **THEN** only that question's answered_value is updated
- **AND** graph_state receives the existing feedback node and edge behavior
- **AND** stage and readiness are recomputed from all questions

#### Scenario: Unknown question
- **WHEN** question_id does not belong to the session
- **THEN** the API SHALL return the standard HTTP 404 error envelope
- **AND** the session SHALL remain unchanged

#### Scenario: Empty answer
- **WHEN** answer is blank after trimming
- **THEN** the API SHALL return HTTP 422
- **AND** the session SHALL remain unchanged

### Requirement: Explicit save semantics
Saving a Lab session SHALL be distinct from generating, quality approval, publication, and adoption.

#### Scenario: Save a generated solution
- **WHEN** a session with generated_solution or solution_json receives a valid save status
- **THEN** the session status and current_stage are updated consistently
- **AND** the response next_action is none for saved, adopted, or archived states

#### Scenario: Save before generation
- **WHEN** a session without a generated solution receives a save request
- **THEN** the API SHALL return HTTP 409 with error code lab_solution_missing
- **AND** SHALL NOT mark the session as saved

### Requirement: Safe client parsing
Frontend consumers SHALL parse known workflow values and safely render unknown values without granting capabilities.

#### Scenario: Unknown stage from server
- **WHEN** a client receives a stage it does not know
- **THEN** it SHALL render an explicit unknown or unsupported state
- **AND** SHALL disable generation and save actions unless the server explicitly grants them
- **AND** SHALL retain the raw stage for diagnostics
