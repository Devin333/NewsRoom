## ADDED Requirements

### Requirement: Paper RAG benchmark supports blind semantic questions
The Paper RAG benchmark SHALL support a `blind_semantic` question profile that hides direct element labels and long copied captions while preserving short natural semantic anchors.

#### Scenario: Blind semantic profile is selected
- **WHEN** the benchmark is run with `--question-profile blind_semantic`
- **THEN** generated QA pairs preserve their gold evidence
- **AND** questions do not expose direct table, figure, or equation labels
- **AND** questions include semantic anchors derived from evidence content or nearby context
- **AND** metadata records the original template question and selected profile

### Requirement: Benchmark reports disclose blind question quality
Benchmark suite reports SHALL include deterministic ambiguity/quality audit metrics for generated questions.

#### Scenario: Benchmark report is written
- **WHEN** a benchmark suite completes
- **THEN** the JSON report includes ambiguity audit metrics
- **AND** the Markdown report summarizes duplicate, ambiguous, missing-anchor, label-leakage, and caption-copy rates

### Requirement: Existing question profiles remain stable
The benchmark SHALL keep the `template` profile as the default and preserve `blind_detemplated` behavior for compatibility.

#### Scenario: Default benchmark run
- **WHEN** no question profile is provided
- **THEN** the benchmark emits the existing template-style questions

#### Scenario: Legacy blind profile is selected
- **WHEN** `blind_detemplated` is selected
- **THEN** the benchmark emits the existing de-templated blind questions
