## MODIFIED Requirements

### Requirement: Persistence configuration is bounded and versioned
The system SHALL use an immutable `GraphArtifactPersistenceConfig` with bounded thresholds, run quotas, tenant quotas, per-`ArtifactClass` quotas, context limits, cache TTL, five-class retention durations, governance alert thresholds, controlled rollout mode, exact current policy version, and explicitly readable rollback policy versions.

#### Scenario: Configuration uses an out-of-range value
- **WHEN** any configured byte, count, ratio, backlog, stampede, TTL, or retention value is below its minimum or above its maximum
- **THEN** configuration construction fails with `result_schema_invalid`

#### Scenario: Aggregate limits are inconsistent
- **WHEN** a configured run limit exceeds its tenant limit or an artifact-class limit exceeds the tenant limit
- **THEN** configuration construction fails before production composition

#### Scenario: Rollback policy is not readable
- **WHEN** a caller selects a policy version absent from the configured readable policy versions
- **THEN** policy construction fails closed as an unsupported version

#### Scenario: Rollout mode is supplied by worker content
- **WHEN** a worker candidate includes a rollout mode, quota override, retention value, alert threshold, or policy version field
- **THEN** result construction rejects the candidate instead of changing configuration
