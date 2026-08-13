## ADDED Requirements

### Requirement: Service resumes Graph from approval

The system SHALL provide an application-service entrypoint that submits a typed resume intent for a decided approval bound to a supported Graph Wait and checksum-verified Graph checkpoint. Harness Graph SHALL decide the resulting node activation.

#### Scenario: Decided approval resumes Graph Wait

- **WHEN** a decided approval references the original Graph run, Wait registration and valid checkpoint
- **THEN** the service validates identity and authorization, submits the resume intent, and returns the resulting Graph run view
- **AND** it does not call a runner or mutate a store directly

#### Scenario: Unsupported Graph is rejected

- **WHEN** a client requests approval resume for an unknown Graph ref, Wait id or profile
- **THEN** the service rejects the request before Graph state mutation

### Requirement: API resumes Graph from approval

The system SHALL expose a versioned HTTP API endpoint for controlled Graph resume from a decided approval.

#### Scenario: API resumes Graph

- **WHEN** a client posts to the Graph approval-resume endpoint with a valid approval id
- **THEN** the response uses the common envelope and contains the resumed Graph run view

### Requirement: CLI resumes Graph from approval

The system SHALL expose a CLI command for controlled Graph resume from a decided approval.

#### Scenario: CLI Graph resume JSON

- **WHEN** an operator invokes the Graph approval-resume command with JSON output
- **THEN** stdout contains the resumed Graph run payload and the command does not construct a control plane directly

### Requirement: MCP and SDK resume Graph from approval

The system SHALL expose controlled approval Graph resume through versioned MCP and SDK surfaces.

#### Scenario: MCP resumes Graph

- **WHEN** an MCP client calls the Graph approval-resume tool
- **THEN** the tool result contains the resumed Graph run view

#### Scenario: Python SDK resumes Graph

- **WHEN** the Python SDK calls approval Graph resume
- **THEN** it posts the Graph run, Wait and checkpoint identity to the versioned Graph resume endpoint
