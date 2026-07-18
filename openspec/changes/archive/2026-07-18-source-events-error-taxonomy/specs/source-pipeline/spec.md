## ADDED Requirements

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
