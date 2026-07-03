## ADDED Requirements

### Requirement: Child candidates are scored through a dedicated scorer module
Paper RAG retrieval SHALL score child candidates through a dedicated child candidate scorer module.

#### Scenario: Field-aware score metadata is preserved
- **WHEN** a child candidate is scored
- **THEN** the scorer returns the scored chunk with field score metadata and child final score metadata matching the retrieval policy

#### Scenario: Citation and formula boosts are preserved
- **WHEN** a citation or formula query is scored
- **THEN** the scorer applies the existing citation claim, element label, and formula sparse boosts without changing metadata keys

#### Scenario: Retriever delegates child scoring
- **WHEN** `ResearchRetriever` scores candidates during retrieval
- **THEN** it delegates to `ChildCandidateScorer` while preserving candidate order and final score values
