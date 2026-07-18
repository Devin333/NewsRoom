## ADDED Requirements

### Requirement: Default source assembly enforces domain rate limits across connectors

Source Pipeline runtime assembly MUST use a shared domain limiter for default-owned connectors so source rate limits apply across connector classes.

#### Scenario: RSS and HTML share a domain

- **GIVEN** a fetch policy with `rate_limit_per_domain_per_minute = 1`
- **AND** an RSS source and an HTML source use the same domain
- **WHEN** the daily source collection step fetches both through default connectors
- **THEN** the first source can fetch
- **AND** the second source is returned as `rate_limited` before network fetch.
