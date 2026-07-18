## ADDED Requirements

### Requirement: Feed fetch failures use stable taxonomy
The system SHALL map feed fetch failures to stable source error taxonomy values.

#### Scenario: Fetch connection fails
- **WHEN** a feed fetch raises a network or connector exception
- **THEN** the returned source error uses `fetch_connection_error`

#### Scenario: Fetch times out
- **WHEN** a feed fetch times out
- **THEN** the returned source error uses `fetch_timeout`

### Requirement: Feed parse failures use parse taxonomy
The system SHALL map feed parser failures to `parse_error`.

#### Scenario: Feed XML is invalid
- **WHEN** fetched feed text cannot be parsed
- **THEN** the returned source error uses `parse_error`

### Requirement: Taxonomy errors preserve original details
The system SHALL preserve original exception details in source error metadata.

#### Scenario: A connector exception is mapped
- **WHEN** the connector maps an exception to a taxonomy error type
- **THEN** metadata includes the original exception type and retryability flag
