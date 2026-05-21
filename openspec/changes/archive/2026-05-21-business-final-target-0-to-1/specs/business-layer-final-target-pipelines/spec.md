## ADDED Requirements

### Requirement: Standard layer pipeline outputs
Each business layer pipeline SHALL return standard result objects with stats, warnings or rejection reasons, evidence-capable metadata, and explainable score or confidence fields where applicable.

#### Scenario: Pipeline result contains diagnostics
- **WHEN** a layer pipeline processes inputs with duplicates, weak evidence, or low confidence
- **THEN** its result exposes accepted outputs plus stats and rejected or warning diagnostics

### Requirement: Output DTO evidence contract
Output DTOs SHALL NOT expose raw payloads and MUST include ranking reason, ranking features, evidence refs, provenance, quality, and feedback references for board cards and run results.

#### Scenario: Board card serializes safely
- **WHEN** a board card is serialized for interfaces
- **THEN** no `raw_payload` field is present and evidence/ranking/quality/provenance fields are available

### Requirement: Dependency direction
Foundation SHALL NOT import layers, layers SHALL NOT import boards, and target-state business layers SHALL NOT import concrete storage implementations.

#### Scenario: Import boundary check
- **WHEN** dependency boundary tests inspect target-state business modules
- **THEN** they find no forbidden imports across foundation, layers, boards, or concrete infrastructure
