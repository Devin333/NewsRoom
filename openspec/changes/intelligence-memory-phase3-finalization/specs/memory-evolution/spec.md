## ADDED Requirements

### Requirement: Phase 3 memory evolution has callable application services
The system SHALL expose graph memory, memory evaluation, feedback submission, and memory policy proposal operations through application service classes with stable `to_dict()` outputs.

#### Scenario: Service returns serializable memory evolution output
- **WHEN** a caller invokes a Phase 3 memory application service
- **THEN** the result can be converted to a dictionary containing the relevant request identifiers and computed payload

### Requirement: Memory consolidation worker payloads are parseable
The system SHALL parse memory consolidation worker payloads into dry-run-first consolidation tasks and execute them through an injected or explicitly configured service.

#### Scenario: Consolidation worker defaults to dry run
- **WHEN** a consolidation payload omits `dry_run`
- **THEN** the parsed task uses `dry_run=True` and does not require mutation permissions

### Requirement: Historian context is consumed by daily reporting and quality metadata
The system SHALL allow daily report writing and quality gate metadata to include prompt-safe historian analysis without replacing evidence or citation checks.

#### Scenario: Historian contradictions are advisory
- **WHEN** historian output contains repeated or contradicted claims
- **THEN** the report and quality outputs include historian metadata but do not block solely because historian metadata exists

### Requirement: Graph projection is observable
The system SHALL summarize read-time graph projections with root, node count, edge count, node type counts, and edge type counts.

#### Scenario: Entity projection summary reports graph shape
- **WHEN** an entity graph projection is summarized
- **THEN** the summary includes the root entity id and typed node and edge counts

### Requirement: Phase 3 loop is integrated
The system SHALL support a deterministic integration loop connecting graph projection, historian analysis, memory evaluation, policy proposal generation, and feedback ingestion.

#### Scenario: Phase 3 loop produces outputs
- **WHEN** a repository provides entity, event, claim, evidence, and feedback persistence methods
- **THEN** the Phase 3 loop can produce historian output, evaluation metrics, policy proposals, and feedback memory ids
