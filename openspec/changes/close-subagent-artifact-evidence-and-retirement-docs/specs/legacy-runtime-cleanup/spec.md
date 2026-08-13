## ADDED Requirements

### Requirement: Historical Agent Session Data Is Operator Owned

After the obsolete agent shared-session runtime is retired, NewsRoom SHALL treat any pre-existing `.newsroom/paper-agent-sessions.sqlite3` or equivalent legacy session database as `orphaned historical data`. Production startup, migrations, cleanup jobs, and replacement Harness code MUST NOT create, read, import, rewrite, archive, or delete that data automatically. A release or operations note MUST state that retention, external archive, and removal are explicit operator decisions subject to local policy.

#### Scenario: NewsRoom starts after retirement

- **WHEN** an installation has no legacy session database or still contains a pre-retirement database
- **THEN** production runtime MUST neither create nor access the retired database path
- **AND** Harness durable transcript startup MUST be independent from that file

#### Scenario: Operator reviews orphaned historical data

- **WHEN** an operator prepares retention or cleanup after the retirement release
- **THEN** the operations note MUST identify the old path and explain that NewsRoom will not delete it automatically
- **AND** the operator MAY retain, externally archive, or remove it only through an explicit out-of-band decision
