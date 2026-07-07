## ADDED Requirements

### Requirement: Live answer eval supports external real-corpus inputs
The live answer evaluation helper SHALL support running against a caller-provided evidence golden set and parsed paper directory.

#### Scenario: External golden set is evaluated without fixture generation
- **WHEN** an operator invokes live answer eval with a `golden_set_path` and `papers_dir`
- **THEN** the helper SHALL pass those paths to evidence eval
- **AND** it SHALL NOT build a new fixture golden set
- **AND** it SHALL run the live gated answer evaluation mode

#### Scenario: Fixture mode remains default
- **WHEN** an operator invokes live answer eval without an external golden set
- **THEN** the helper SHALL create fixture papers
- **AND** it SHALL build a fixture golden set before running live gated answer evaluation

### Requirement: Live answer eval CLI exposes real-corpus options
The `run-live-answer-eval` command SHALL expose external corpus options that route to the live answer evaluation helper.

#### Scenario: CLI passes external input paths
- **WHEN** an operator runs `python -m scripts.dev run-live-answer-eval --golden-set data/eval/golden_set.json --papers-dir .newsroom/papers`
- **THEN** the CLI SHALL pass both paths to the live answer evaluation helper
- **AND** the result payload SHALL identify the external golden set path

### Requirement: Scheduled workflow attempts real-corpus live eval when artifacts exist
The live answer eval workflow SHALL keep fixture coverage and attempt real-corpus coverage when parsed paper artifacts are available.

#### Scenario: Real-corpus artifacts absent
- **WHEN** the scheduled workflow runs without `.newsroom/papers`
- **THEN** it SHALL still run the fixture-backed live answer eval when LLM secrets exist
- **AND** it SHALL skip the real-corpus step with a clear message

#### Scenario: Real-corpus artifacts present
- **WHEN** the scheduled workflow runs with `.newsroom/papers` and LLM secrets exist
- **THEN** it SHALL invoke `python -m scripts.dev run-live-answer-eval --golden-set data/eval/golden_set.json --papers-dir .newsroom/papers`
