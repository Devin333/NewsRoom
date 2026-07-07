## ADDED Requirements

### Requirement: Evidence eval exposes a structured core API
Evidence evaluation SHALL expose a library-callable core API that accepts structured options instead of CLI argv strings.

#### Scenario: Library caller invokes evidence eval with options
- **WHEN** a business evaluation helper needs to run evidence eval in process
- **THEN** it SHALL call the structured core API with an options object
- **AND** it SHALL NOT build argv strings for another CLI entrypoint

### Requirement: Evidence eval CLI remains compatible
The existing evidence eval CLI SHALL preserve its accepted flags and return-code behavior.

#### Scenario: CLI command delegates through parsed options
- **WHEN** an operator invokes `run_evidence_eval` with existing flags
- **THEN** the CLI SHALL parse those flags into structured options
- **AND** it SHALL delegate to the same core API used by library callers

### Requirement: Live and CI evaluation helpers avoid CLI direction coupling
Live answer evaluation and CI eval gate helpers SHALL use the structured evidence eval API for in-process execution.

#### Scenario: Live answer eval runs fixture or external corpus mode
- **WHEN** live answer eval runs evidence evaluation
- **THEN** it SHALL pass structured options including live retrieval, live answer eval, thresholds, and corpus inputs
- **AND** it SHALL preserve fixture and external corpus behavior

#### Scenario: CI eval gate runs deterministic answer eval
- **WHEN** the CI eval gate runs evidence evaluation
- **THEN** it SHALL pass structured options including fixture generation, deterministic answer eval, and the configured threshold
- **AND** it SHALL preserve existing gate pass/fail semantics
