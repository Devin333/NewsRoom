## MODIFIED Requirements

### Requirement: AI review is auxiliary after deterministic source comparison
The system SHALL run AI review only as auxiliary diagnostics after deterministic source comparison and SHALL NOT use AI review verdicts as publication gates.

#### Scenario: AI review fails but source comparison passes
- **WHEN** Asset Gate passes, source comparison passes, and the AI reviewer returns a non-approval verdict
- **THEN** the repository SHALL publish the document with status `compiled`
- **AND** the compile status SHALL retain the review report and warning diagnostics.

#### Scenario: AI review is unavailable but source comparison passes
- **WHEN** Asset Gate passes, source comparison passes, and the AI reviewer is unavailable
- **THEN** the repository SHALL publish the document with status `compiled`
- **AND** the compile status SHALL retain the unavailable review report and warning diagnostics.

### Requirement: Source comparison controls Reader publication
The system SHALL compare compiled Reader output against native paper/source invariants before publication and SHALL block publication on hard source-comparison failures.

#### Scenario: Compiled output is source-traceable
- **WHEN** a compiled document has real paper metadata, readable body blocks, source coordinates, complete figure/table assets, and valid source PDF/page references
- **THEN** source comparison SHALL pass
- **AND** the repository SHALL store a source comparison report with metrics, warnings, and learned lessons.

#### Scenario: Compiled output is missing reader-critical content or visuals
- **WHEN** a compiled document has no readable body, missing figure/table assets, invalid source coordinates, missing source PDF references, or missing required paper identity
- **THEN** source comparison SHALL fail with hard errors
- **AND** the repository SHALL NOT publish the document body to readers.
