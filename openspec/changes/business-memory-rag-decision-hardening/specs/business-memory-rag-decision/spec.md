## ADDED Requirements

### Requirement: Business Memory Decision Context
The business layer SHALL provide memory hit and context models that can convert recalled memory into deterministic scoring features.

#### Scenario: Empty memory is score neutral
- **WHEN** no memory search port is configured
- **THEN** memory recall returns an empty context and zero-impact feature values without raising an error

### Requirement: Memory Features For Board Scoring
Board scoring SHALL be able to merge optional memory features into a card feature vector.

#### Scenario: Memory features affect scoring
- **WHEN** memory context reports duplicate risk, reliable source history, topic momentum, or prior misrank penalties
- **THEN** the produced feature vector includes those values for scoring recipes or diagnostics

### Requirement: Memory Search Port Boundary
Business memory recall SHALL use an abstract search port and SHALL NOT import concrete vector clients.

#### Scenario: Search results are normalized
- **WHEN** the search port returns dict-like or object-like search results
- **THEN** business memory converts them into `BusinessMemoryHit` values
