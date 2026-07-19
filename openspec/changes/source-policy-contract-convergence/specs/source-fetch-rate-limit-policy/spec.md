## MODIFIED Requirements

### Requirement: Source connectors enforce per-domain fetch rate limits
The system SHALL use the infrastructure Source fetch policy as the single
implementation of per-domain rate-limit decisions. A default process composition
SHALL give Source connectors, Source tools, and Source health probes access to
one thread-safe underlying reservation ledger, and every denial SHALL occur
before external network access.

#### Scenario: Same-domain fetch exceeds rate limit
- **WHEN** the shared limiter has already reserved the configured number of
  fetches for a domain within the one-minute window
- **THEN** the next connector, tool, or health fetch for that domain returns a
  `rate_limited` decision or SourceError
- **AND** the external fetcher is not called

#### Scenario: Other domains remain available
- **WHEN** one domain reaches the configured rate limit
- **THEN** a fetch for a different domain is still allowed

#### Scenario: Window reset allows another fetch
- **WHEN** the oldest reservation exits the one-minute window
- **THEN** a new fetch for that domain is allowed

#### Scenario: Domain key is entry-point independent
- **WHEN** HTTP and HTTPS URLs with different paths, queries, fragments, case,
  or ports resolve to the same hostname
- **THEN** all Source entry points reserve the same case-folded domain bucket

#### Scenario: arXiv provider hosts share one quota
- **WHEN** Source metadata uses `export.arxiv.org` and Research source-package
  or PDF retrieval uses `arxiv.org`
- **THEN** all calls reserve the canonical `arxiv.org` provider bucket
- **AND** other provider subdomains remain distinct unless explicitly declared
  by this contract

#### Scenario: Concurrent reservations cannot exceed the bucket
- **GIVEN** one reservation remains in the configured domain budget
- **WHEN** concurrent Source entry points attempt to reserve that domain
- **THEN** exactly one reservation is allowed
- **AND** all other decisions are denied without a network call

#### Scenario: Retries consume one logical reservation
- **WHEN** one allowed logical Source fetch performs multiple retry attempts
- **THEN** the limiter records exactly one reservation for that logical fetch
- **AND** both eventual success and eventual failure keep that reservation until
  the window expires
