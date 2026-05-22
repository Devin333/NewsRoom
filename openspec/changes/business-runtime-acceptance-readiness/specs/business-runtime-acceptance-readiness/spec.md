## ADDED Requirements

### Requirement: Offline business runtime acceptance
The interface layer SHALL provide an offline business acceptance service that can verify productized board runs, artifacts, subscriptions, feedback, improvements, cross-board aggregation, weekly enhanced outputs, and eval suite readiness.

#### Scenario: Full acceptance runs offline
- **WHEN** the full acceptance service is invoked with fixture data
- **THEN** it returns an AcceptanceResult with checks, summary, artifact root, and passed/partial/failed status without real network or LLM access

### Requirement: Business acceptance CLI
The CLI SHALL expose `news business acceptance` subcommands that call the acceptance service and can output either human-readable summaries or JSON.

#### Scenario: Acceptance CLI emits JSON
- **WHEN** `news business acceptance --json` is invoked
- **THEN** it prints the serialized AcceptanceResult and exits successfully when checks pass

### Requirement: Productized artifact schema acceptance
Productized board artifacts SHALL be validated for existence, parseability, stable metadata, subscription readiness, quality summary fields, improvement proposal status, and non-empty summary markdown.

#### Scenario: Board artifact schema check
- **WHEN** a productized board run completes
- **THEN** required artifacts exist and contain board_type, run_id, schema_version, quality, subscription, and improvement fields

### Requirement: Durable improvement proposal readiness
The local JSON improvement proposal store SHALL persist proposal status transitions across instances and support both directory and explicit JSON file paths.

#### Scenario: Approved proposal survives store reload
- **WHEN** a proposal is saved and approved in a LocalJsonImprovementProposalStore
- **THEN** a new store instance reads the approved proposal and status filtering works

### Requirement: Productized subscription consumption
SubscriptionApplicationService SHALL build delivery plans from board and cross-board productized subscription payloads without sending notifications.

#### Scenario: Delivery plan from payload
- **WHEN** a productized subscription payload is provided
- **THEN** the service returns a DeliveryPlan dictionary suitable for downstream delivery routing
