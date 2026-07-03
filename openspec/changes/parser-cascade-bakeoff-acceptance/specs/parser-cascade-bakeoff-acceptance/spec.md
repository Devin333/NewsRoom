## ADDED Requirements

### Requirement: Parser bake-off reports include penalized parser metrics
Parser bake-off reports SHALL include penalized metrics for each parser that combine raw parser quality, optional RAG quality, and explicit penalties.

#### Scenario: Penalized metrics are written
- **WHEN** a parser bake-off report is built for one or more parser artifact directories
- **THEN** each parser payload SHALL include `penalized_metrics`
- **AND** `penalized_metrics` SHALL include `raw_quality_score`, `penalty_total`, `penalized_quality_score`, and `penalty_details`

#### Scenario: Failed ingest reduces penalized score
- **WHEN** an ingest manifest reports failed or missing requested papers
- **THEN** the parser's penalty details SHALL include an ingest failure penalty
- **AND** the penalized quality score SHALL be lower than the raw quality score

### Requirement: Parser bake-off reports expose cascade acceptance checks
Parser bake-off reports SHALL expose acceptance checks for parser cascade artifacts using configurable thresholds.

#### Scenario: Cascade acceptance passes
- **WHEN** the parser named `cascade` meets the minimum requested paper count, parse success, locator coverage, and RAG thresholds
- **THEN** report recommendations SHALL mark `cascade_acceptance.ready` as true
- **AND** all cascade acceptance checks SHALL have status `pass`

#### Scenario: Cascade acceptance fails
- **WHEN** the parser named `cascade` fails any acceptance threshold
- **THEN** report recommendations SHALL mark `cascade_acceptance.ready` as false
- **AND** the failing checks SHALL record actual and threshold values

### Requirement: Parser bake-off CLI accepts acceptance threshold overrides
The parser bake-off report CLI SHALL allow callers to override cascade acceptance thresholds.

#### Scenario: Override threshold from CLI
- **WHEN** `run_parser_bakeoff_report` is called with `--acceptance-threshold min_requested_papers=10`
- **THEN** the generated report SHALL evaluate cascade acceptance with `min_requested_papers` equal to 10

#### Scenario: Invalid threshold form is rejected
- **WHEN** `run_parser_bakeoff_report` is called with an acceptance threshold that is not `KEY=VALUE`
- **THEN** the CLI SHALL raise a validation error before writing the report

### Requirement: Parser bake-off Markdown surfaces penalized and acceptance results
Parser bake-off Markdown reports SHALL surface penalized score and cascade acceptance results for human review.

#### Scenario: Markdown includes penalized table
- **WHEN** a parser bake-off Markdown report is written
- **THEN** it SHALL include a parser scoring section with penalized score and total penalty

#### Scenario: Markdown includes cascade acceptance
- **WHEN** a parser bake-off Markdown report is written
- **THEN** it SHALL include cascade acceptance check statuses
