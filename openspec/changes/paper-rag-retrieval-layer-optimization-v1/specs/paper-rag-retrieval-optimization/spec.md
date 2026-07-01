## ADDED Requirements

### Requirement: Paper RAG exposes top-k retrieval diagnostics
Paper RAG benchmark reports SHALL expose `@3`, `@5`, and `@10` metrics for strict hit rate, equivalent hit rate, evidence coverage, source locator coverage, MRR, and nDCG diagnostics where the underlying metric supports the requested `k`.

#### Scenario: Benchmark report includes top-k metrics
- **WHEN** a Paper RAG benchmark suite is generated
- **THEN** the candidate report includes retrieval metrics for `@3`, `@5`, and `@10`
- **AND** the markdown summary presents enough `@3` and `@5` values to diagnose whether evidence is usable by the answer stage

### Requirement: Hybrid retrieval policy is explicitly gated
Paper RAG SHALL provide a named hybrid retrieval policy that can be selected without changing the default retrieval policy.

#### Scenario: Hybrid policy is selected
- **WHEN** the retrieval policy name is `paper_hybrid_rrf_rag_v1`
- **THEN** retrieval uses hybrid candidate fusion behavior
- **AND** the report metadata records the selected policy name

#### Scenario: Default policy remains compatible
- **WHEN** no hybrid policy is selected
- **THEN** existing default retrieval behavior remains available

### Requirement: Hybrid retrieval fuses multiple candidate channels
The hybrid Paper RAG policy SHALL fuse semantic, field, sparse lexical, claim, and visual candidate channels when those channels are available.

#### Scenario: Sparse candidate improves recall
- **WHEN** a query contains exact formula, table, caption, or terminology tokens
- **THEN** sparse lexical recall contributes candidate chunks even if dense retrieval ranks them lower
- **AND** the candidate metadata records sparse/RRF score components

#### Scenario: RRF avoids raw score calibration
- **WHEN** multiple retrieval channels return the same chunk with different score scales
- **THEN** the hybrid policy combines ranked channel positions through reciprocal-rank-style contribution
- **AND** the candidate keeps per-channel contribution metadata

### Requirement: Evidence graph expansion preserves paired evidence
Paper RAG SHALL expand table, figure, formula, and result evidence to paired context needed for multi-evidence answering.

#### Scenario: Table evidence expands to result context
- **WHEN** a table chunk is selected for a table or numerical result query
- **THEN** retrieval considers nearby context, referenced-by chunks, and result/conclusion paragraphs as paired evidence
- **AND** expanded chunks include `expansion_edge`, `expanded_from_chunk_id`, and `graph_score` metadata

#### Scenario: Formula evidence expands to explanation context
- **WHEN** a formula chunk is selected for a formula query
- **THEN** retrieval considers formula description, referenced text, and explanation paragraphs as paired evidence
- **AND** expanded chunks remain deduplicated by chunk id

#### Scenario: Figure evidence expands to visual context
- **WHEN** a figure chunk is selected for a figure query
- **THEN** retrieval considers caption, visual description, nearby context, and referenced-by chunks as paired evidence

### Requirement: Source locators survive retrieval expansion
Paper RAG SHALL preserve source locator metadata across supplemental, expanded, parent, and snippet chunks.

#### Scenario: Expanded chunk inherits locator when needed
- **WHEN** an expanded chunk lacks its own `source_locator` and the anchor chunk has one
- **THEN** the expanded chunk receives the inherited locator
- **AND** metadata records `source_locator_inherited=true` and `source_locator_origin_chunk_id`

#### Scenario: Existing locator is not overwritten
- **WHEN** an expanded chunk already has its own `source_locator`
- **THEN** retrieval keeps the expanded chunk locator
- **AND** no inherited locator flag is added
