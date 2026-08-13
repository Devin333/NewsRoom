## MODIFIED Requirements

### Requirement: Run Response Separates Interface And Runtime Status

The system SHALL expose a `RunResponse` with API view `status` and optional `task_status`, `run_status`, `report_status`, `run_id`, `task_id`, `report_id`, and `message` fields. A synchronous orchestrated run SHALL expose Graph run status without requiring a Workflow runtime status or identity.

#### Scenario: Async daily run returns queued task status

- **WHEN** a caller submits an async daily run through the generic run API
- **THEN** the response has `status` set to `queued` and `task_status` set to the worker task status without requiring a Graph run status

#### Scenario: Synchronous run returns Graph status

- **WHEN** a caller submits a synchronous Graph run through the generic run API
- **THEN** the response includes `run_status` alongside the interface `status`
- **AND** no Workflow identity is required or returned

### Requirement: Interface Entrypoints Use Application Services

CLI, API, MCP, and SDK entrypoints SHALL call application services or HTTP interface methods for business and Graph run actions instead of bypassing into Graph control-plane internals, executors, stores, or retired Workflow runtime modules.

#### Scenario: API run routes use application services

- **WHEN** an API caller submits daily, weekly or Graph run requests
- **THEN** the API dispatches through worker or Graph run application services

#### Scenario: MCP run tools use application services

- **WHEN** an MCP caller invokes run tools
- **THEN** the MCP service dispatches through configured run or worker application services

#### Scenario: Interface imports are scanned

- **WHEN** architecture tests scan interface entrypoints and services
- **THEN** they contain no import from `framework.workflow` and do not directly construct a Graph scheduler or store
