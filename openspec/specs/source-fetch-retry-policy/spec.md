# source-fetch-retry-policy Specification

## Purpose
TBD - created by archiving change source-fetch-retry-policy. Update Purpose after archive.
## Requirements
### Requirement: Source fetch policy retries transient fetch failures
The system SHALL retry transient fetch failures according to `SourceFetchPolicy`
before returning a final fetch error.

#### Scenario: HTTP 5xx succeeds after retry
- **WHEN** a source fetch receives a retryable HTTP 5xx error and a later attempt
  succeeds within `retry_times`
- **THEN** the connector returns fetched source items without a source error

#### Scenario: HTTP 4xx is not configured for retry
- **WHEN** a source fetch receives a non-retryable HTTP 4xx error
- **THEN** the connector returns the structured fetch error after one attempt

#### Scenario: Retry attempts are exhausted
- **WHEN** all retry attempts fail with a retryable fetch exception
- **THEN** the connector returns the final structured fetch error with attempt
  metadata
