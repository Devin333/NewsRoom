## ADDED Requirements

### Requirement: Source Health Probes Respect Rate Limits

Source health probe execution SHALL enforce configured domain rate limits before external network access.

#### Scenario: Two health probes target the same limited domain

- **GIVEN** a source health checker with `rate_limit_per_domain_per_minute` set to `1`
- **AND** two enabled sources on the same domain
- **WHEN** a health check run evaluates both sources
- **THEN** the first probe may fetch
- **AND** the second probe SHALL be skipped before network access with a `rate_limited` diagnostic
- **AND** the skipped probe SHALL NOT increment source failure counts.
