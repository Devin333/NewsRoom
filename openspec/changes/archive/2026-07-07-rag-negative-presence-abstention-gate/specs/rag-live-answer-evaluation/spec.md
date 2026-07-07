## MODIFIED Requirements

### Requirement: Evidence CLI supports live gated answer evaluation
The evidence evaluation CLI SHALL provide a live answer evaluation mode that scores generated answers from the gated Harness answer path.

#### Scenario: Running live answer evaluation
- **WHEN** `run_evidence_eval` is invoked with `--live-answer-eval`
- **THEN** answer metrics are computed from gated answer payloads rather than deterministic synthetic samples
- **AND** the evidence report metadata records `answer_eval_mode` as `live`

#### Scenario: Context-absence phrases count as abstentions
- **WHEN** live answer generation or answer evaluation receives text stating that the provided context does not state an answer
- **OR** the text states that the provided context contains no mention of the requested information
- **THEN** the text SHALL be classified as an abstention
- **AND** expected-abstain samples using those phrases SHALL count as correct abstentions

#### Scenario: Negative presence recitations count as abstentions
- **WHEN** a live Paper answer asks whether a paper includes, specifies, reports, discusses, provides, states, mentions, describes, or contains a requested subject
- **AND** the generated answer does not explicitly abstain
- **AND** the generated answer has insufficient overlap with the requested subject terms
- **THEN** the runtime SHALL publish an abstained answer candidate instead of the unrelated generated answer
- **AND** the candidate metadata SHALL record that negative presence relevance normalization was applied
