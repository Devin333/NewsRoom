## ADDED Requirements

### Requirement: Service resumes Graph from approval

The system SHALL provide an application-service entrypoint that resolves a decided approval into a typed cause bound to the current durable Graph Wait. Harness SHALL commit the cause before automatically resuming evaluation and SHALL exclusively decide the resulting node activation.

#### Scenario: Decided approval resumes Graph Wait

- **WHEN** a decided approval references the original Graph run and current durable Wait registration
- **THEN** the service validates approval evidence, actor identity, scope and authorization, submits the typed cause, and returns the resulting Graph run view
- **AND** it does not call a runner or mutate a store directly
- **AND** it accepts no caller-supplied node update, checkpoint override, resume metadata or route

#### Scenario: Unsupported Graph is rejected

- **WHEN** a client requests approval resume for an unknown Graph ref, Wait id or profile
- **THEN** the service rejects the request before Graph state mutation

### Requirement: API resumes Graph from approval

The system SHALL expose a versioned HTTP API endpoint that submits a decided approval to the Graph application service; resume remains an automatic Harness consequence of the durable cause.

#### Scenario: API resumes Graph

- **WHEN** a client posts to the Graph approval-decision endpoint with a valid approval id
- **THEN** the response uses the common envelope and contains the resumed Graph run view

### Requirement: CLI resumes Graph from approval

The system SHALL expose a CLI command that submits a decided approval through the Graph application service.

#### Scenario: CLI Graph resume JSON

- **WHEN** an operator invokes the Graph approval-decision command with JSON output
- **THEN** stdout contains the resumed Graph run payload and the command does not construct a control plane directly

### Requirement: MCP and SDK resume Graph from approval

The system SHALL expose Graph approval-decision submission through versioned MCP and SDK surfaces while Harness retains automatic resume authority.

#### Scenario: MCP resumes Graph

- **WHEN** an MCP client calls the Graph approval-decision tool
- **THEN** the tool result contains the resumed Graph run view

#### Scenario: Python SDK resumes Graph

- **WHEN** the Python SDK calls approval Graph resume
- **THEN** it posts the approval id and Graph run/Wait identity to the versioned approval-decision endpoint without a state patch or route
