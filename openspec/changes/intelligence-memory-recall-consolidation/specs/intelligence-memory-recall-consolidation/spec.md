## ADDED Requirements

### Requirement: Intelligence memory supports structured recall queries
The system SHALL expose structured intelligence memory query protocols for exact lookup, topic/entity timelines, claim evidence lookup, decisions, and preferences.

#### Scenario: Recall repository can query memory layers
- **WHEN** a recall service is configured with a query repository
- **THEN** it can retrieve evidence, claims, entities, events, decisions, and preferences through structured repository methods

### Requirement: Claims are consolidated deterministically
The system SHALL merge duplicate claims, update confidence from supporting evidence, and mark contradictory claims without requiring LLM extraction.

#### Scenario: Duplicate claims merge evidence
- **WHEN** a new claim matches an existing claim by normalized text or subject/predicate/object
- **THEN** consolidation returns a merged claim with combined evidence IDs and recalculated confidence

#### Scenario: Contradictory claims are marked
- **WHEN** a new claim contradicts an existing claim by deterministic contradiction rules
- **THEN** consolidation marks the result claim as contradicted and records the evidence or reason

### Requirement: Memory events produce timelines
The system SHALL build deterministic memory events and expose topic and entity timelines.

#### Scenario: Topic timeline is generated
- **WHEN** events exist for a topic
- **THEN** the timeline service returns timeline items ordered by event time or detection time

#### Scenario: Entity timeline is generated
- **WHEN** events are linked to an entity
- **THEN** the timeline service returns only events related to that entity

### Requirement: Recall v2 returns prompt-ready historical context
The system SHALL plan recall intent and return an IntelligenceMemoryContext that can render known claims, recent timeline, supporting evidence, entity profiles, previous decisions, and conflict warnings.

#### Scenario: Recall without repository remains safe
- **WHEN** recall is requested without a query repository
- **THEN** the service returns an empty context containing the query and memory unavailable metadata

#### Scenario: Recall with repository includes conflicts
- **WHEN** recalled claims contain active and contradicted claims for the same subject and predicate
- **THEN** the context includes conflict warning metadata and prompt context includes conflicts or warnings

### Requirement: Memory features and quality checks are deterministic services
The system SHALL provide callable memory ranking features and quality memory checks without changing the main ranking or quality gate path.

#### Scenario: Ranking features are computed
- **WHEN** feature input contains topic, source, entity, claim, or event identifiers
- **THEN** the feature computer returns bounded source reliability, momentum, importance, novelty, duplicate, contradiction, and previous quality signals

#### Scenario: Quality checks report memory issues
- **WHEN** claims or events are unsupported, contradicted, or duplicate
- **THEN** the quality checker returns typed issues and fails the result for critical issues

### Requirement: Intelligence ingestion performs Phase 2 processing
The system SHALL extend intelligence memory ingestion to resolve entities, consolidate claims, build events, save final bundle layers, and index final bundle objects.

#### Scenario: Ingestion result includes Phase 2 metadata
- **WHEN** intelligence ingestion processes run output
- **THEN** the result keeps legacy indexing fields and includes metadata for entity resolution, claim consolidation, and event building
