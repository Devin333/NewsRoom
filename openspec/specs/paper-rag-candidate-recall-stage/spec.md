# paper-rag-candidate-recall-stage Specification

## Purpose
TBD - created by archiving change extract-candidate-recall-stage. Update Purpose after archive.
## Requirements
### Requirement: Candidate recall is delegated to a dedicated stage
Paper RAG retrieval SHALL run candidate recall through a dedicated candidate recall stage.

#### Scenario: Dense recall returns merged candidates and query variants
- **WHEN** hybrid RRF is disabled
- **THEN** the stage returns dense text candidates, query variants, and recall counts matching the previous retriever behavior

#### Scenario: Hybrid RRF fuses text, field, claim, and visual rankings
- **WHEN** hybrid RRF is enabled for the routed intent
- **THEN** the stage fuses available channel rankings using the existing RRF algorithm and preserves hybrid metadata

#### Scenario: Optional channels degrade to empty hits
- **WHEN** field, claim, or visual indexes are unavailable
- **THEN** the stage returns empty hit lists without changing text candidates
