## MODIFIED Requirements

### Requirement: Standard layer pipeline outputs
Each business layer pipeline SHALL return standard result objects with stats, warnings or rejection reasons, evidence-capable metadata, and explainable score or confidence fields where applicable. Extraction, relation, and analysis pipelines MUST orchestrate named helper modules rather than requiring callers or tests to use private pipeline methods for core behavior.

#### Scenario: Pipeline result contains diagnostics
- **WHEN** a layer pipeline processes inputs with duplicates, weak evidence, or low confidence
- **THEN** its result exposes accepted outputs plus stats and rejected or warning diagnostics

#### Scenario: Helper modules are independently testable
- **WHEN** extractor, linker, and analyzer classes are called directly with valid business objects
- **THEN** they return deterministic outputs without calling private pipeline methods

## ADDED Requirements

### Requirement: Deterministic explainable layer helpers
Named extractor, linker, and analyzer modules SHALL expose deterministic rules with feature metadata that explains the produced confidence or score.

#### Scenario: Helper output explains its score
- **WHEN** a helper creates an entity, relation candidate, trend, quality, maturity, impact, or radar item
- **THEN** the output includes confidence, score, metadata, warning, or reason fields sufficient for debugging and tests
