# architecture-boundary-governance Specification

## Purpose
TBD - created by archiving change architecture-p0-boundary-hardening. Update Purpose after archive.
## Requirements
### Requirement: Framework specs do not depend on workflow runtime
The system SHALL keep framework specification models free of imports from workflow runtime modules.

#### Scenario: Status terminal checks
- **WHEN** callers evaluate step or workflow terminal status from `framework.specs`
- **THEN** the result is computed without importing `framework.workflow.runtime`

### Requirement: Skill Runtime ownership is explicit
The system SHALL keep Skill Runtime implementation under `framework.skills` and prevent business, infrastructure, or interface imports from entering that package.

#### Scenario: Skill Runtime boundary test
- **WHEN** architecture boundary tests inspect Skill Runtime imports
- **THEN** forbidden layer imports are reported as failures

### Requirement: Infrastructure memory dependency debt is tracked
The system SHALL explicitly list current infrastructure modules that depend on business memory models until a port/DTO migration removes them.

#### Scenario: Known debt visibility
- **WHEN** architecture tests inspect infrastructure memory and graph modules
- **THEN** only listed legacy dependency paths are allowed

### Requirement: Business research does not depend on interface layers
The system SHALL keep `business/research` free of direct imports from `interfaces`, including business-owned RAG evaluation CLIs.

#### Scenario: Live answer eval uses business-owned assembly
- **WHEN** `run_evidence_eval --live-answer-eval` runs with parsed paper chunks from `--papers-dir`
- **THEN** the live answer ask callable is assembled from business-owned RAG session components without importing `interfaces`
- **AND** answer evaluation receives gated Harness payload semantics for conversion into `EvidenceAnswerSample`

#### Scenario: Live answer eval without fixture chunks fails closed
- **WHEN** `run_evidence_eval --live-answer-eval` is requested without parsed fixture chunks and no outer-layer ask callable is injected
- **THEN** the command fails with a clear configuration error instead of importing `interfaces` or production stores from `business/research`
