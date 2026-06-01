## ADDED Requirements

### Requirement: Source comparison reports are durable artifacts
The Research Reader compiler SHALL store a durable source comparison report for every compile attempt that reaches the comparison stage.

#### Scenario: Comparison report is written
- **WHEN** a compile reaches source comparison
- **THEN** the compiler SHALL persist `source-comparison-report.json`
- **AND** the compile status SHALL expose report summary fields including pass/fail, metrics, errors, warnings, and lessons.

### Requirement: Source comparison lessons feed memory
The Research Reader compiler SHALL convert source comparison outcomes into intelligence memory so repeated formatting, content, and visual failures can be avoided in later compiles.

#### Scenario: Comparison produces reusable lessons
- **WHEN** source comparison produces pass or fail lessons
- **THEN** the compiler SHALL create EvidenceMemory records for observed source fidelity facts
- **AND** create DecisionMemory records for publication/blocking decisions
- **AND** create EventMemory records for reader-source-comparison learning events.

#### Scenario: Memory backend is unavailable
- **WHEN** source comparison finishes but the memory repository is not configured or fails
- **THEN** the compile SHALL keep the source comparison report artifact, diagnostics, and a replayable local memory journal
- **AND** the compile SHALL NOT fail solely because memory storage is unavailable.

### Requirement: Source comparison practices are reusable
The system SHALL maintain a reusable skill or practice document for Reader source comparison.

#### Scenario: Skill document exists
- **WHEN** a developer or agent needs to improve paper reader compilation
- **THEN** the repository SHALL contain a reusable paper reader source-comparison skill describing source-first metadata, AI layout, deterministic native-paper comparison, visual completeness checks, and memory learning expectations.
