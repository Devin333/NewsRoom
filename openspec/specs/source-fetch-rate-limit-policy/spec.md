# source-fetch-rate-limit-policy Specification

## Purpose
TBD - created by archiving change source-fetch-rate-limit-policy. Update Purpose after archive.
## Requirements
### Requirement: Source connectors enforce per-domain fetch rate limits
The system SHALL enforce `rate_limit_per_domain_per_minute` before source
connector fetch paths call external fetchers.

#### Scenario: Same-domain fetch exceeds rate limit
- **WHEN** a connector has already reserved the configured number of fetches for
  a domain within the one-minute window
- **THEN** the next fetch for that domain returns a `rate_limited` `SourceError`
  without calling the fetcher

#### Scenario: Other domains remain available
- **WHEN** one domain reaches the configured rate limit
- **THEN** a fetch for a different domain is still allowed

#### Scenario: Window reset allows another fetch
- **WHEN** the oldest reservation exits the one-minute window
- **THEN** a new fetch for that domain is allowed
