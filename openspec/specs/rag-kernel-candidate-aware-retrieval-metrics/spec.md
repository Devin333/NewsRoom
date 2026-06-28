# rag-kernel-candidate-aware-retrieval-metrics Specification

## Purpose
TBD - created by archiving change rag-kernel-research-eval-migration. Update Purpose after archive.
## Requirements
### Requirement: Retrieval metrics support candidate evidence groups
The RAG kernel retrieval metrics SHALL support ranked evidence items that represent multiple candidate evidence ids without requiring domain-specific evaluators to reimplement Hit@K, MRR, coverage, or nDCG.

#### Scenario: One retrieved evidence maps to multiple gold ids
- **WHEN** a retrieval metric case includes `ranked_evidence_id_candidates`
- **THEN** Hit@K, reciprocal rank, evidence coverage, and nDCG use those candidate groups for matching
- **AND** the metrics still return the same values for cases that only provide `ranked_evidence_ids`

### Requirement: Retrieval metrics support candidate source locator groups
The RAG kernel retrieval metrics SHALL support ranked source locator candidate groups so one evidence item can represent multiple source spans or source references.

#### Scenario: Source locator prefix match is scored
- **WHEN** a gold source locator is a stable prefix of a more specific ranked locator
- **THEN** source locator coverage treats the ranked locator as matching the gold locator
- **AND** the metric remains domain-neutral by operating only on generic locator strings

### Requirement: Research evidence evaluation delegates generic metrics
Research evidence evaluation SHALL delegate generic retrieval metrics to `framework/rag/evaluation` and keep only paper-specific metrics in Research.

#### Scenario: Paper evidence aggregation uses kernel metrics
- **WHEN** `EvidenceRetrievalEvaluator` aggregates answerable samples
- **THEN** Hit@K, MRR, evidence coverage, source locator coverage, and nDCG are calculated through framework retrieval metric functions
- **AND** required type coverage, image recall, visual evidence coverage, citation accuracy, overlap citation accuracy, and over-retrieval remain Research-owned

### Requirement: Evaluation migration does not change benchmark behavior
The migration SHALL preserve existing Paper RAG benchmark output shape and metric values for equivalent inputs.

#### Scenario: Existing evidence eval tests run
- **WHEN** Research evidence evaluation tests run after the migration
- **THEN** existing multi-evidence, fixed-window mapping, source locator, image recall, citation, and negative QA expectations still pass

