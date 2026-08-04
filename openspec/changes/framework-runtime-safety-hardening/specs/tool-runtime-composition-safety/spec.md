## ADDED Requirements

### Requirement: Control delegation uses the canonical worker task contract
`control.delegate_to_subagent` SHALL enqueue `framework.workers.models.Task` with canonical task status, retry, lease, serialization, and queue semantics. Framework Tool code SHALL NOT maintain a second Task implementation.

#### Scenario: Agent delegates work through the control tool
- **WHEN** the control tool accepts a valid delegation request
- **THEN** the queue receives an instance of the canonical worker `Task`
- **AND** its task id, type, queue, payload, attempts, metadata, and status survive worker serialization

#### Scenario: Delegated task reaches an in-memory worker
- **WHEN** a delegated canonical task is leased by `InMemoryTaskQueue` and a matching handler is registered
- **THEN** `WorkerLoop` executes the handler and completes the lease
- **AND** the task is not stranded because of a same-name type mismatch

#### Scenario: Legacy Tool import requests Task
- **WHEN** a caller imports the compatibility `Task` symbol from the Tool built-in surface
- **THEN** that symbol resolves to the canonical worker Task class

### Requirement: Built-in tools have one registration owner
Every built-in tool name SHALL be registered by exactly one owning composition layer, and registry conflict rejection SHALL remain fail-closed.

#### Scenario: Dangerous business catalog is built
- **WHEN** Tool discovery includes dangerous and network tools
- **THEN** `web.search` appears exactly once
- **AND** the catalog validates with no duplicate tool names

#### Scenario: Custom web search provider is configured
- **WHEN** business composition receives a custom web search provider
- **THEN** it forwards that provider to the single infrastructure-owned `web.search` registration
- **AND** does not install a second executor

#### Scenario: CLI exports dangerous schemas
- **WHEN** `tools list --include-dangerous` or `tools schema --include-dangerous` runs
- **THEN** the command succeeds with a conflict-free deterministic catalog
