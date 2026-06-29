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

### Requirement: Answer context hydrates evidence packs after same-group hits

Paper RAG answer generation SHALL be able to hydrate missing same-group evidence into the answer context after retrieval hits at least one evidence chunk from that group.

#### Scenario: Hydrating primary evidence from an interpretation hit

- **WHEN** retrieval returns an interpretation chunk that belongs to a QA pair's `supporting_evidence_group`
- **AND** the group's primary evidence chunk is available from deterministic chunk lookup
- **THEN** answer context assembly SHALL add the primary evidence chunk as an evidence-pack expansion candidate
- **AND** the expansion metadata SHALL include `evidence_group_id`, `expanded_from_chunk_id`, `expansion_reason`, and `evidence_group_role`
- **AND** answer sample metadata SHALL include evidence-pack required ids and expanded chunk ids

#### Scenario: No same-group hit

- **WHEN** retrieval does not return any chunk in a QA pair's `supporting_evidence_group`
- **THEN** answer context hydration SHALL NOT inject the group's gold chunks
- **AND** missing gold evidence SHALL remain observable in evaluation metadata

### Requirement: Citation retrieval supports claim-level search

Paper RAG citation retrieval SHALL support deterministic claim-level search while preserving source chunk ids for strict evidence evaluation.

#### Scenario: Claim records map back to source chunks

- **WHEN** the system builds a claim index from paper chunks
- **THEN** each claim record SHALL include `claim_id`, `paper_id`, `chunk_id`, `claim_text`, `claim_type`, and `source_locator`
- **AND** claim ids SHALL be stable for the same paper, source chunk, and claim text

#### Scenario: Citation route uses claim hits

- **WHEN** a citation query asks for the passage grounding a paper claim
- **AND** the claim index finds a matching claim sentence
- **THEN** retrieval SHALL map the claim hit back to its source chunk
- **AND** the returned chunk metadata SHALL include `claim_index_hit`, `claim_index_score`, `claim_id`, and `claim_text`
- **AND** retrieval metadata SHALL report `claim_index_hits`
