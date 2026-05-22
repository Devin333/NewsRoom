## ADDED Requirements

### Requirement: Structured memory has a graph projection
The system SHALL expose graph nodes, edges, expansions, paths, and graph queries over structured intelligence memory without requiring a graph database.

#### Scenario: Entity graph expansion returns related memory
- **WHEN** a graph store expands an entity node
- **THEN** the expansion includes related event, claim, and evidence nodes and their typed edges where repository data is available

### Requirement: Historical context is deterministic
The system SHALL build historical context from recall, timeline, and optional graph services using deterministic rules.

#### Scenario: Historian summarizes topic history
- **WHEN** a historian analyzes a topic with known events and claims
- **THEN** the output includes a timeline summary, repeated or contradicted claims, and recommendations

### Requirement: Memory quality can be evaluated
The system SHALL compute memory quality metrics and return an evaluation report with warnings and recommendations.

#### Scenario: Evaluation report scores memory health
- **WHEN** a memory evaluator receives a topic or entity request
- **THEN** it returns support, contradiction, duplicate, usefulness, noise, timeline, regret, and false-positive metrics

### Requirement: Memory consolidation is dry-run first
The system SHALL expose consolidation tasks for entity merge, claim status refresh, event dedupe, timeline summary, source reliability update, and noise cleanup.

#### Scenario: Consolidation emits proposed changes
- **WHEN** a consolidation task runs in dry-run mode
- **THEN** it reports scanned, changed, skipped, warnings, and proposed changes without mutating memory

### Requirement: Human feedback becomes memory
The system SHALL convert human feedback into preference and decision memory records when supported by the feedback type.

#### Scenario: Source feedback creates preference memory
- **WHEN** source boost or source block feedback is ingested
- **THEN** the service saves a source preference and records the generated preference ID

### Requirement: Policy learning only proposes changes
The system SHALL generate adaptive memory policy proposals from evaluation reports without automatically applying high-risk changes.

#### Scenario: High-risk proposal requires approval
- **WHEN** policy learning proposes a high-risk threshold change
- **THEN** the proposal requires human approval and cannot auto-apply
