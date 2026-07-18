## ADDED Requirements

### Requirement: Source exception classification has one business owner
The system SHALL use one business-owned Source taxonomy for error type, health,
workflow, operator, and non-fetch semantic decisions across connector fetch,
connector parse, business normalization, Source tools, and Source health probes.
For fetch and probe exceptions, the final `retryable` value SHALL come only from
the effective infrastructure `SourceFetchRetryDecision`. Infrastructure adapters
SHALL NOT implement a second taxonomy decision table.

#### Scenario: Same exception has entry-point parity
- **WHEN** the same exception, phase, and extension input are classified by a
  connector, Source tool, and health probe under the same fetch policy
- **THEN** every entry point returns the same error type, retryable flag,
  health-affecting flag, workflow-blocking flag, and operator-action flag

#### Scenario: Infrastructure taxonomy adapter is behavior-free
- **WHEN** an infrastructure connector imports the Source taxonomy adapter
- **THEN** its decision is produced by the business-owned classifier
- **AND** the adapter contains no fallback classification table

#### Scenario: Parse taxonomy matrix is deterministic
- **WHEN** the input is malformed feed XML, an invalid published date, or another
  parse exception
- **THEN** the error type is respectively `invalid_feed`,
  `invalid_published_at`, or `parse_error`
- **AND** retryable, health-affecting, workflow-blocking, and operator-action
  flags are all false

#### Scenario: Processing phase taxonomy matrix is deterministic
- **WHEN** the phase is normalize, dedup, or rank
- **THEN** the error type is respectively `normalization_error`, `dedup_error`,
  or `ranking_error`
- **AND** retryable, health-affecting, workflow-blocking, and operator-action
  flags are all false

#### Scenario: Deterministic fetch policy errors are non-retryable
- **WHEN** the input is unsupported content type, too many redirects, explicit
  robots denial, or maximum bytes exceeded
- **THEN** the error type is respectively `unsupported_content_type`,
  `too_many_redirects`, `robots_disallowed`, or `max_bytes_exceeded`
- **AND** retryable, health-affecting, workflow-blocking, and operator-action
  flags are all false

#### Scenario: Invalid connector configuration requires operator action
- **WHEN** a `ValueError` matches a declared invalid-configuration keyword
- **THEN** the error type is `invalid_source_config`
- **AND** retryable, health-affecting, and workflow-blocking are false
- **AND** operator-action is true

#### Scenario: HTTP taxonomy uses effective retry policy
- **WHEN** an HTTP 4xx or HTTP 5xx exception is classified
- **THEN** the error type is respectively `fetch_http_4xx` or `fetch_http_5xx`
- **AND** health-affecting is true
- **AND** workflow-blocking and operator-action are false
- **AND** retryable equals the effective infrastructure fetch retry decision

#### Scenario: Transport taxonomy is deterministic
- **WHEN** the input is a timeout, another `URLError`, or another unclassified
  fetch exception
- **THEN** the error type is respectively `fetch_timeout`,
  `fetch_connection_error`, or `fetch_connection_error`
- **AND** retryable and health-affecting are true
- **AND** workflow-blocking and operator-action are false

### Requirement: Connector taxonomy extensions are explicit
Connector-specific invalid-configuration keywords and diagnostic inputs MUST be
passed through an immutable taxonomy extension contract. A connector MUST NOT
override canonical type, health, workflow, or operator decisions, or an
effective fetch retry decision, after classification.

#### Scenario: Connector-specific configuration error
- **WHEN** a connector classifies a `ValueError` matching one of its declared
  invalid-configuration keywords
- **THEN** the canonical classification is `invalid_source_config`
- **AND** `retryable` is false
- **AND** `operator_action_required` is true

#### Scenario: Unmatched extension does not change canonical fallback
- **WHEN** a connector exception matches no declared extension input
- **THEN** the canonical classifier applies its normal phase and exception matrix

### Requirement: Source connectors share error envelope construction
Infrastructure Source connectors SHALL use one shared SourceError factory for
source identity, taxonomy decisions, policy metadata, request/response refs,
occurrence time, and connector diagnostics. Connector-specific parsers MAY add
diagnostics but SHALL NOT duplicate the envelope constructor.

#### Scenario: Connector diagnostics survive shared construction
- **WHEN** a connector maps an exception with status, attempt, redirect, robots,
  content-type, or provider diagnostics
- **THEN** the shared factory preserves those diagnostics in metadata
- **AND** it preserves the canonical classification fields

#### Scenario: Diagnostics cannot override reserved policy fields
- **WHEN** connector diagnostics contain `retryable`,
  `source_health_affecting`, `workflow_blocking`, or
  `operator_action_required`
- **THEN** shared error construction rejects the conflicting diagnostics
- **AND** no ambiguous SourceError is emitted

#### Scenario: All production connectors use the factory
- **WHEN** production connector modules are inspected after cutover
- **THEN** no connector-local `_source_error` envelope constructor remains

## MODIFIED Requirements

### Requirement: Feed fetch failures use stable taxonomy
The system SHALL map non-HTTP connection and otherwise unclassified feed fetch
exceptions to `fetch_connection_error`, timeouts to `fetch_timeout`, HTTP 4xx to
`fetch_http_4xx`, and HTTP 5xx to `fetch_http_5xx`. Fetch retryability SHALL come
from the effective infrastructure retry decision.

#### Scenario: Fetch connection fails
- **WHEN** a feed fetch raises a non-HTTP network or unclassified connector
  exception
- **THEN** the returned Source error uses `fetch_connection_error`

#### Scenario: Fetch times out
- **WHEN** a feed fetch times out
- **THEN** the returned Source error uses `fetch_timeout`

#### Scenario: Fetch receives HTTP client error
- **WHEN** a feed fetch receives an HTTP 4xx error
- **THEN** the returned Source error uses `fetch_http_4xx`
- **AND** retryable equals the effective infrastructure retry decision

#### Scenario: Fetch receives HTTP server error
- **WHEN** a feed fetch receives an HTTP 5xx error
- **THEN** the returned Source error uses `fetch_http_5xx`
- **AND** retryable equals the effective infrastructure retry decision

### Requirement: Feed parse failures use parse taxonomy
The system SHALL map malformed feed envelopes, including XML `ParseError`, to
`invalid_feed`; it SHALL map a generic feed item parse failure that is not an
invalid feed or invalid published date to `parse_error`.

#### Scenario: Feed XML is invalid
- **WHEN** fetched feed text cannot be parsed as a feed envelope
- **THEN** the returned Source error uses `invalid_feed`

#### Scenario: Generic feed item parse fails
- **WHEN** a feed item parser fails for a reason outside the invalid-feed and
  invalid-date rules
- **THEN** the returned Source error uses `parse_error`

### Requirement: Taxonomy errors preserve original details
The system SHALL preserve original exception details and canonical policy
decisions in Source error metadata, regardless of connector or entry point.

#### Scenario: A connector exception is mapped
- **WHEN** the shared Source error factory maps an exception to a taxonomy error
  type
- **THEN** metadata includes the original exception type and retryability flag
- **AND** metadata includes canonical health, workflow, and operator policy fields
