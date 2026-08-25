# interfaces-contracts Specification

## Purpose
TBD - created by archiving change interfaces-p0-contract-models. Update Purpose after archive.
## Requirements
### Requirement: Shared Public Contract Models
The system SHALL expose public interface request, response, error, pagination, run, and report models from `interfaces.models` as the canonical model surface for API, CLI, MCP, SDK, and webhook boundaries.

#### Scenario: API model compatibility imports use shared models
- **WHEN** callers import public API models through `interfaces.api.models`
- **THEN** those imports resolve to the same classes exported by `interfaces.models`

### Requirement: Stable API Error Envelope
The system SHALL wrap API errors in a stable envelope containing `success`, `error`, `request_id`, and `schema_version`, where `error` includes `code`, `message`, `details`, `retryable`, `user_action_required`, and `request_id`.

#### Scenario: Validation error returns contract shape
- **WHEN** an API request fails validation
- **THEN** the response body contains the shared error envelope and preserves the request id

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

### Requirement: Write API Audit Events
The system SHALL emit redacted audit records for write API requests through the interface audit emitter.

#### Scenario: Run submission emits write audit
- **WHEN** a caller submits a run through a write API endpoint
- **THEN** the audit record contains actor context, action, resource type, request id, status result, and redacted metadata

### Requirement: CLI entrypoint remains compatible
The system SHALL preserve the public `interfaces.cli.news` command entrypoint while allowing command implementation modules to be split internally.

#### Scenario: Existing callers use news main
- **WHEN** callers invoke `interfaces.cli.news.main` with existing arguments
- **THEN** the command behavior and output format remain compatible

#### Scenario: Existing parser construction
- **WHEN** callers import and invoke `interfaces.cli.news.build_parser`
- **THEN** the returned parser supports existing commands and options

### Requirement: CLI commands remain compatible during module split
The system SHALL preserve existing CLI command names, options, exit codes, and JSON/human output formats while command handlers move into grouped modules.

#### Scenario: Existing CLI tests
- **WHEN** existing CLI tests invoke commands through `interfaces.cli.news.main`
- **THEN** all command behaviors remain compatible
