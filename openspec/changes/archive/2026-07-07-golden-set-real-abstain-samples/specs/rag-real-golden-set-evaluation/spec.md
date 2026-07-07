## ADDED Requirements

### Requirement: Real golden set has explicit behavior labels
The repository real-corpus RAG golden set SHALL label each row with an `expected_behavior` value.

#### Scenario: Loading repository golden rows
- **WHEN** `data/eval/golden_set.json` is loaded through the evidence golden set loader
- **THEN** every loaded pair has `expected_behavior` set to either `answer` or `abstain`

### Requirement: Real golden set includes abstain samples
The repository real-corpus RAG golden set SHALL include abstain samples so abstention metrics can run on real-corpus data.

#### Scenario: Counting real-corpus behavior labels
- **WHEN** the repository golden set is inspected
- **THEN** `expected_behavior_counts["answer"]` is greater than zero
- **AND** `expected_behavior_counts["abstain"]` is at least 10

### Requirement: Golden set rebuilds use the current evidence model
The golden set rebuild entrypoint SHALL use the current evidence-evaluation model and SHALL support negative QA generation.

#### Scenario: Building a new evidence golden set
- **WHEN** `data/eval/build_golden_set.py` is run with its default configuration
- **THEN** it builds `EvidenceQAPair` rows with negative samples enabled
- **AND** it writes rows using the evidence golden set serializer
