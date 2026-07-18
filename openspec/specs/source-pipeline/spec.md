# source-pipeline Specification

## Purpose
TBD - created by archiving change source-pipeline-final-target-closure. Update Purpose after archive.
## Requirements
### Requirement: Final Source Connector Protocol
The system SHALL expose a target-state `SourceConnector` protocol with async `fetch` and `parse` methods and a `SourceFetchContext`.

#### Scenario: Sync connectors remain compatible
- **WHEN** a current sync connector is wrapped by the adapter
- **THEN** it can be invoked through the target-state protocol shape

### Requirement: Explicit Source Lineage
Raw, normalized, and ranked source items SHALL expose explicit lineage while preserving metadata lineage.

#### Scenario: Normalization preserves lineage
- **WHEN** a raw source item is normalized
- **THEN** the normalized item has a top-level lineage object and metadata lineage

### Requirement: Final Health Down State
Source health SHALL use `down` for failed sources in cooldown.

#### Scenario: Cooldown after repeated failures
- **WHEN** a source reaches the failure threshold
- **THEN** its health status is `down` and `cooldown_until` is set

### Requirement: Final Ranking Signals
Ranking SHALL include duplicate cluster size, historical importance, and subscription match in the score breakdown.

#### Scenario: Ranking metadata explains score
- **WHEN** source items are ranked
- **THEN** ranked metadata includes the expanded score breakdown

### Requirement: Source Pipeline Events And Error Taxonomy

The system SHALL emit Source Pipeline events for fetch, parse, health, cooldown,
probe, normalization, deduplication, and ranking phases, and SHALL classify
source errors through a single taxonomy.

#### Scenario: Source parse succeeds

- **WHEN** connector execution returns raw source items
- **THEN** the workflow records parse started and parse succeeded events

#### Scenario: Source enters cooldown

- **WHEN** a health-affecting source failure reaches the cooldown threshold
- **THEN** the workflow records a source cooldown started event

### Requirement: Default source assembly enforces domain rate limits across connectors

Source Pipeline runtime assembly MUST use a shared domain limiter for default-owned connectors so source rate limits apply across connector classes.

#### Scenario: RSS and HTML share a domain

- **GIVEN** a fetch policy with `rate_limit_per_domain_per_minute = 1`
- **AND** an RSS source and an HTML source use the same domain
- **WHEN** the daily source collection step fetches both through default connectors
- **THEN** the first source can fetch
- **AND** the second source is returned as `rate_limited` before network fetch.

### Requirement: Source Health Probes Respect Rate Limits

Source health probe execution SHALL enforce configured domain rate limits before external network access.

#### Scenario: Two health probes target the same limited domain

- **GIVEN** a source health checker with `rate_limit_per_domain_per_minute` set to `1`
- **AND** two enabled sources on the same domain
- **WHEN** a health check run evaluates both sources
- **THEN** the first probe may fetch
- **AND** the second probe SHALL be skipped before network access with a `rate_limited` diagnostic
- **AND** the skipped probe SHALL NOT increment source failure counts.
