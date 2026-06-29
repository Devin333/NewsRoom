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

### Requirement: Answer evaluation exposes evidence-pack diagnostics

Paper RAG answer evaluation SHALL expose detailed diagnostics without replacing existing answer success and canonical failure reason metrics.

#### Scenario: Diagnostics distinguish true missing from equivalent support

- **WHEN** an answer sample cites or uses equivalent evidence but not the strict gold chunk id
- **THEN** answer evaluation SHALL report `equivalent_gold_supported`
- **AND** it SHALL add a diagnostic tag for `gold_id_missed_but_equivalent_supported`
- **AND** it SHALL continue to report strict and equivalent coverage separately

#### Scenario: Evidence pack context gaps are visible

- **WHEN** answer context misses required primary evidence or all interpretation context from the supporting evidence group
- **THEN** answer evaluation SHALL add `context_missing_primary_evidence` or `context_missing_interpretation_evidence`
- **AND** report JSON SHALL include aggregated `diagnostic_tag_counts`
- **AND** answer samples SHALL include per-sample `diagnostic_tags`

#### Scenario: Claim support is measured for citation QA

- **WHEN** a citation QA pair has deterministic `gold_claim_ids`
- **AND** the selected answer context carries matching claim metadata
- **THEN** answer evaluation SHALL report `claim_support_coverage`
- **AND** promotion checklist SHALL include a claim-support visibility check

### Requirement: Promotion checks include strict/equivalent and diagnostic gates

Paper RAG promotion checklist SHALL include evidence-pack and answer-diagnostic checks in addition to existing retrieval and answer success gates.

#### Scenario: Promotion report includes diagnostic checks

- **WHEN** benchmark suite builds a policy promotion checklist
- **THEN** the checklist SHALL include `strict_equivalent_hit_at_10_gap`
- **AND** it SHALL include `true_missing_gold_rate`
- **AND** it SHALL include `answer_diagnostics`
- **AND** it SHALL include `claim_support_coverage`

### Requirement: Held-out benchmark matrix can run multiple paper sets

Paper RAG SHALL provide a benchmark matrix runner for multiple held-out paper datasets using the same benchmark suite semantics.

#### Scenario: Matrix runner writes aggregate report

- **WHEN** the runner receives two or more named paper datasets
- **THEN** it SHALL run the benchmark suite once per dataset
- **AND** it SHALL write `benchmark_matrix_report.json`
- **AND** it SHALL write `benchmark_matrix_report.md`
- **AND** the aggregate report SHALL include per-dataset Hit@10, equivalent Hit@10, MRR, answer success, warnings, and promotion readiness

#### Scenario: Matrix manifest requires real held-out artifacts

- **WHEN** the runner receives a dataset manifest
- **THEN** it SHALL load every named dataset entry
- **AND** it SHALL fail before running if any required `papers_dir` is missing
- **AND** it SHALL fail before running if any required dataset has no `research_document.json` artifacts
