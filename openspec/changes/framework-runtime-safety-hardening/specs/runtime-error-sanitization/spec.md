## ADDED Requirements

### Requirement: Unknown MCP failures use a safe public projection
MCP service, HTTP, resource, prompt, and stdio boundaries SHALL replace unknown internal exceptions with a stable public error type, fixed bounded message, and optional correlation error id. They SHALL NOT expose raw exception text, traceback, credentials, DSNs, paths, payloads, or implementation-only exception types.

#### Scenario: Tool handler raises an unknown exception containing a secret
- **WHEN** an MCP tool call raises an unclassified internal exception
- **THEN** Tool, HTTP MCP, and stdio responses identify a stable internal error
- **AND** no part of the exception text or secret appears on the wire

#### Scenario: Prompt or resource handler raises an unknown exception
- **WHEN** prompt retrieval or resource reading fails with an unclassified exception
- **THEN** the same safe projection is applied before constructing the MCP result

### Requirement: Approved typed MCP failures remain compatible
The safe projection SHALL preserve explicitly approved validation, not-found, authorization, and artifact integrity error types and their documented safe public messages.

#### Scenario: Artifact checksum verification fails
- **WHEN** an artifact or replay operation raises `ArtifactChecksumMismatchError`, `ArtifactStoreMetadataError`, or `ArtifactStoreRequiredError`
- **THEN** the MCP result preserves that typed error contract and approved safe message
- **AND** contains no artifact contents or arbitrary exception diagnostics

#### Scenario: Unknown tool is requested
- **WHEN** a caller requests an unregistered MCP tool, resource, or prompt
- **THEN** the existing not-found error type and bounded identifier message are preserved

### Requirement: Dead-letter records contain only safe failure diagnostics
Worker dead-letter persistence SHALL store only allow-listed error classification, fixed or already-approved safe message, retry/operator flags, attempts, timestamps, and a correlation error id. Final DLQ serialization SHALL sanitize the assembled task, reason, error, and event payload regardless of caller behavior.

#### Scenario: Worker exception contains a DSN or token
- **WHEN** retry exhaustion moves the task to Redis DLQ
- **THEN** the serialized stream record and its nested last event contain no raw exception text, DSN, token, credential, traceback, or secret task field
- **AND** the record retains a stable error type and error id for server-side correlation

#### Scenario: Safe dead letter is read and requeued
- **WHEN** an operator lists and requeues a sanitized dead-letter record
- **THEN** its safe typed classification and attempt count round-trip
- **AND** no original secret is reconstructed or copied into task metadata

### Requirement: Raw internal diagnostics stay server-side
Unknown exception details SHALL be emitted only through structured server-side logging or telemetry with bounded correlation identifiers and SHALL not be persisted or returned by public adapters.

#### Scenario: Internal MCP failure is projected
- **WHEN** the boundary creates a safe internal error result
- **THEN** the server diagnostic can correlate request/tool/task and error id
- **AND** public output contains only the safe projection
