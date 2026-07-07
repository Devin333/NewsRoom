# rag-abstention-failure-taxonomy Specification

## Purpose
TBD - created by archiving change rag-overconservative-abstention-taxonomy. Update Purpose after archive.
## Requirements
### Requirement: RAG evaluation distinguishes abstention failure direction
The Paper RAG evaluation taxonomy SHALL report answerable samples that abstain as `abstained_over_conservative`, and expected-abstain samples that answer as `abstention_wrong`.

#### Scenario: Answerable sample abstains
- **WHEN** a benchmark sample has `expected_behavior=answer`
- **AND** the evaluated answer is marked as an abstention
- **THEN** the sample failure reasons SHALL include `abstained_over_conservative`
- **AND** the sample failure reasons SHALL NOT include `abstention_wrong`

#### Scenario: Expected-abstain sample answers
- **WHEN** a benchmark sample has `expected_behavior=abstain`
- **AND** the evaluated answer is not marked as an abstention
- **THEN** the sample failure reasons SHALL include `abstention_wrong`
- **AND** the sample failure reasons SHALL NOT include `abstained_over_conservative`

### Requirement: RAG reports aggregate the over-conservative abstention reason
Paper RAG benchmark reports SHALL preserve `abstained_over_conservative` in per-sample failure details, aggregate reason counts, and generated fix manifests.

#### Scenario: Report contains over-conservative abstention
- **WHEN** a benchmark report includes a sample classified with `abstained_over_conservative`
- **THEN** the report SHALL include that reason in its failure reason counts
- **AND** generated fix manifest entries SHALL retain that reason for the affected sample
