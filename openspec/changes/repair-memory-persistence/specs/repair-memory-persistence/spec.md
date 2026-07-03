## ADDED Requirements

### Requirement: Reader repair memory supports implementation-independent listing
`ReaderRepairService` SHALL consolidate repair cases through the `ReaderRepairMemoryPort` contract rather than reading in-memory implementation fields.

#### Scenario: Service uses a port-backed case list
- **WHEN** reader repair completes with any `ReaderRepairMemoryPort` implementation
- **THEN** consolidation SHALL use cases returned by `list_cases()`
- **AND** the service SHALL not require a `.cases` dictionary on the memory implementation

### Requirement: Reader repair memory persists to PostgreSQL
The infrastructure layer SHALL provide a PostgreSQL implementation of `ReaderRepairMemoryPort`.

#### Scenario: Repair case is persisted and recalled
- **WHEN** a `ReaderRepairCase` is written through the PostgreSQL repository
- **THEN** the active memory object SHALL be stored in PostgreSQL
- **AND** recall by matching issue type or error signature SHALL return the serialized case as a domain model

#### Scenario: Repair strategy is persisted and recalled
- **WHEN** a `ReaderRepairStrategy` with a promoted memory status is written
- **THEN** recall by issue type SHALL return the strategy as a domain model

### Requirement: Reader repair memory is versioned and rollbackable
Reader repair memory writes SHALL preserve append-only version history and support restoring a previous version.

#### Scenario: Case rollback restores a previous version
- **WHEN** a prior case version exists
- **AND** `rollback_case()` is called for that version
- **THEN** the repository SHALL make that payload active again
- **AND** append a new rollback version instead of deleting history

#### Scenario: Strategy rollback restores a previous version
- **WHEN** a prior strategy version exists
- **AND** `rollback_strategy()` is called for that version
- **THEN** the repository SHALL make that payload active again
- **AND** append a new rollback version instead of deleting history

### Requirement: Production composition can use persistent reader repair memory
The interface composition layer SHALL expose an env-based factory for Postgres-backed reader repair memory.

#### Scenario: Database DSN is configured
- **WHEN** `NEWS_DATABASE_DSN` is set
- **THEN** the factory SHALL build `ReaderRepairService` with `PostgresReaderRepairMemoryRepository`

#### Scenario: Database DSN is absent
- **WHEN** `NEWS_DATABASE_DSN` is not set
- **THEN** the memory factory SHALL return `None`
