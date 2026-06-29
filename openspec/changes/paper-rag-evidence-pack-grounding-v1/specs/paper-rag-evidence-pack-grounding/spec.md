## ADDED Requirements

### Requirement: Evidence QA pairs carry evidence groups

Paper RAG benchmark QA pairs SHALL carry deterministic evidence-group metadata while preserving existing strict gold chunk ids.

#### Scenario: Golden set contains evidence group fields

- **WHEN** Paper RAG builds an answerable QA pair from paper chunks
- **THEN** the pair SHALL include `supporting_evidence_group_id`
- **AND** it SHALL include `equivalent_gold_chunk_ids`
- **AND** it SHALL preserve `gold_chunk_ids` unchanged for strict metrics

### Requirement: Equivalent evidence is structure-bound

Equivalent gold evidence SHALL be derived only from deterministic paper structure and lineage.

#### Scenario: Equivalent evidence generation

- **WHEN** the benchmark expands a gold chunk
- **THEN** it MAY include same-paper parent, referenced, nearby, or same-locator chunks
- **AND** it MUST NOT include chunks from another paper
- **AND** it MUST NOT include arbitrary semantic neighbors without a structural relation

### Requirement: Retrieval reports compare strict and equivalent coverage

Paper RAG retrieval reports SHALL expose strict and equivalent evidence coverage side by side.

#### Scenario: Retrieval evaluation with equivalent evidence

- **WHEN** retrieval is evaluated for a QA pair with equivalent gold ids
- **THEN** strict metrics SHALL continue to use `gold_chunk_ids`
- **AND** equivalent metrics SHALL use `equivalent_gold_chunk_ids`
- **AND** the report SHALL include both strict and equivalent coverage fields

### Requirement: Answer evaluation recognizes equivalent grounding

Answer evaluation SHALL distinguish true missing gold from equivalent evidence support.

#### Scenario: Answer cites equivalent supporting evidence

- **WHEN** an answer cites or uses a chunk that is in `equivalent_gold_chunk_ids` but not in `gold_chunk_ids`
- **AND** the answer facts match
- **THEN** the answer evaluation SHALL report equivalent coverage
- **AND** it SHALL NOT classify the sample as `missing_gold_in_retrieval`
- **AND** strict gold coverage SHALL still be reported separately
