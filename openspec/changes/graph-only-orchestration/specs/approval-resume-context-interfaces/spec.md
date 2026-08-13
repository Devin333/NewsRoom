## MODIFIED Requirements

### Requirement: API exposes approval resume context

The system SHALL expose a versioned HTTP API endpoint that returns Graph approval resume context for a decided approval.

#### Scenario: Decided approval context

- **WHEN** a client requests resume context for an approved, rejected, or modified Graph approval
- **THEN** the response includes `graph_run_id`, `node_instance_id`, `graph_checkpoint_ref`, validated `node_updates`, `resume_metadata`, and the selected `decision_key`

#### Scenario: Pending approval context is unavailable

- **WHEN** a client requests resume context for a pending approval
- **THEN** the API returns a unified error response indicating the resume context is unavailable

### Requirement: CLI exposes approval resume context

The system SHALL provide a CLI command that prints Graph approval resume context for a decided approval.

#### Scenario: CLI JSON output

- **WHEN** an operator invokes the versioned Graph approval resume-context command with JSON output
- **THEN** stdout contains the same Graph run/node/checkpoint context as the application service

### Requirement: MCP exposes approval resume context

The system SHALL provide a versioned MCP tool for Graph approval resume context.

#### Scenario: MCP tool returns context

- **WHEN** an MCP client calls the Graph approval resume-context tool for a decided approval
- **THEN** the tool result contains Graph identity, validated `node_updates`, and `resume_metadata`

### Requirement: SDK clients expose approval resume context

The system SHALL expose Graph approval resume context retrieval through supported versioned SDK client surfaces.

#### Scenario: Python SDK request

- **WHEN** the Python SDK requests Graph approval resume context
- **THEN** it posts the configured `decision_key` and Graph identity to the versioned Graph resume-context endpoint
