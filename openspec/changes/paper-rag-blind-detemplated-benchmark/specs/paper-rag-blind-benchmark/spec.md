## ADDED Requirements

### Requirement: Paper RAG benchmark supports de-templated blind questions
The Paper RAG benchmark SHALL support a profile that generates natural questions without directly exposing table labels, figure labels, equation labels, long caption excerpts, or full quoted claim snippets.

#### Scenario: Blind question profile is selected
- **WHEN** the benchmark is run with the blind de-templated profile
- **THEN** generated QA pairs preserve the same gold evidence
- **AND** questions are rewritten into natural user-style prompts
- **AND** pair metadata records the original template question and selected profile

### Requirement: Template benchmark remains the default regression profile
The benchmark SHALL keep the existing template question generation behavior unless the blind de-templated profile is explicitly selected.

#### Scenario: Default benchmark run
- **WHEN** no question profile is provided
- **THEN** the benchmark emits the existing template-style questions

### Requirement: Reports disclose question profile
Benchmark suite reports SHALL include the selected question profile so template-regression metrics and blind-test metrics are not mixed.

#### Scenario: Benchmark report is written
- **WHEN** a benchmark suite completes
- **THEN** the JSON and Markdown reports identify the question profile and blind/de-templating policy
