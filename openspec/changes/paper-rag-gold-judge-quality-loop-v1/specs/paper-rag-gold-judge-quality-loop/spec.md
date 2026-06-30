## ADDED Requirements

### Requirement: Benchmark matrix passes gold and answer judge configuration

Paper RAG benchmark matrix SHALL pass gold judge and answer judge settings into each dataset benchmark suite.

#### Scenario: Matrix CLI enables LLM gold judge

- **WHEN** the matrix CLI receives `--gold-judge llm`
- **THEN** each dataset suite SHALL run with `gold_judge_mode="llm"`
- **AND** the matrix summary SHALL include gold judge quality metrics per dataset
- **AND** blind semantic runs with a judge report SHALL NOT emit `blind_semantic_without_gold_judge`

### Requirement: Gold judge sampling is stratified and deterministic

Gold evidence judge sampling SHALL cover QA types deterministically before filling remaining slots.

#### Scenario: Stratified gold judge sample

- **WHEN** audit items contain multiple QA types and `gold_judge_sample_size` is positive
- **THEN** judge items SHALL include at least one item per available target QA type before duplicates by type are selected
- **AND** ordering SHALL be stable for the same `split_seed`
- **AND** warning/fail audit items SHALL be prioritized within their QA type

### Requirement: Human spot-check annotations are structured

Human spot-check annotation summaries SHALL validate the expected annotation schema and expose QA-type metrics.

#### Scenario: Structured annotations are summarized

- **WHEN** a spot-check annotations JSONL file is provided
- **THEN** the report SHALL count labels by `pass`, `warning`, `fail`, and `needs_fix`
- **AND** it SHALL report `pass_rate`, warning count, fail count, schema error count, and `by_qa_type`

### Requirement: Promotion checklist includes gold quality

Paper RAG promotion SHALL include gold judge quality and optional human spot-check quality checks.

#### Scenario: Gold judge quality gate

- **WHEN** a blind semantic suite has a gold judge report
- **THEN** promotion checklist SHALL include `gold_judge_quality`
- **AND** it SHALL fail if any gold judge item failed
- **AND** it SHALL fail if the pass rate or error rate violates configured thresholds

#### Scenario: Blind semantic without gold judge is visible

- **WHEN** a blind semantic suite has no gold judge report
- **THEN** promotion checklist SHALL include `gold_judge_quality`
- **AND** the check SHALL be `warning`
- **AND** ready-for-promotion SHALL be false for strict gold-quality promotion

### Requirement: Gold judge failures produce repair artifacts

Paper RAG benchmark suite SHALL write repair artifacts for gold judge warning, failure, and error items.

#### Scenario: Judge failures are exported

- **WHEN** gold judge returns warning, failure, or error items
- **THEN** the suite output SHALL include `gold_judge_failures.jsonl`
- **AND** it SHALL include `gold_judge_warnings.jsonl`
- **AND** it SHALL include `gold_fix_manifest.json` with action counts and item summaries
