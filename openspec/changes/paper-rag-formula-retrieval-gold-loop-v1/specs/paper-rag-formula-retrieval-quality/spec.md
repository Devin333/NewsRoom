## ADDED Requirements

### Requirement: Formula metadata is normalized for retrieval
Paper RAG SHALL derive deterministic formula metadata from formula chunks so LaTeX formatting differences do not prevent formula retrieval.

#### Scenario: Formula metadata is extracted
- **WHEN** a formula chunk contains LaTeX with labels, operators, symbols, and layout commands
- **THEN** the system records raw LaTeX, normalized LaTeX, formula symbols, formula operators, formula structure tokens, formula reference labels, and formula context terms
- **AND** the normalized metadata excludes layout-only commands such as `\left`, `\right`, labels, tags, and spacing commands where possible

#### Scenario: Formula field text includes normalized metadata
- **WHEN** field text is extracted for a formula chunk
- **THEN** the `equation` field includes normalized LaTeX, symbols, operators, structure tokens, reference labels, and referenced explanation text when present

### Requirement: Formula sparse scoring contributes to formula retrieval
Paper RAG SHALL calculate formula-specific sparse score components for formula-intent queries and expose those components in retrieved chunk metadata.

#### Scenario: Formula query matches symbols and operators
- **WHEN** a formula query mentions symbols or operators from a formula chunk
- **THEN** the formula chunk receives formula symbol, operator, context, and aggregate sparse score metadata
- **AND** the aggregate formula sparse score can contribute to the final retrieval score under a formula-specific policy

#### Scenario: Equation label match is boosted
- **WHEN** a query refers to a specific equation label or number
- **THEN** chunks with matching `reference_labels`, `equation_id`, `equation_label`, or formula reference labels are ranked ahead of unrelated formula chunks when other signals are comparable

### Requirement: Formula retrieval policy is explicit
Paper RAG SHALL provide a named retrieval policy for formula optimization without changing default retrieval behavior.

#### Scenario: Formula policy is selected
- **WHEN** retrieval uses `paper_formula_rag_v1`
- **THEN** the policy enables formula sparse scoring, field reranking, formula graph expansion, and formula-specific score weights
- **AND** the default policy remains unchanged

### Requirement: Formula explanation context is graph-expanded
Paper RAG SHALL retrieve formula chunks and explanatory context together for formula explanation questions.

#### Scenario: Formula chunk expands to explanations
- **WHEN** a formula-intent retrieval hit is a formula chunk
- **THEN** the system can add bounded explanation chunks from formula referenced text, explicit references, nearby explanation context, and parent context
- **AND** each expanded chunk includes `expansion_reason`, `expanded_from_chunk_id`, `graph_score`, and source locator preservation metadata when available

#### Scenario: Explanation chunk can recover formula evidence
- **WHEN** a formula-intent retrieval hit is an explanatory paragraph linked to a formula
- **THEN** the linked formula chunk can be included in the retrieved evidence set with graph expansion metadata

### Requirement: Formula failures are diagnosable
Paper RAG benchmark outputs SHALL expose formula retrieval failure reasons and score components.

#### Scenario: Formula benchmark failure is reported
- **WHEN** a formula QA sample misses gold evidence in the reported top-k window
- **THEN** the report can identify whether the likely failure is formula normalization, sparse scoring, label matching, graph expansion, reranker demotion, or bad gold evidence
- **AND** the sample includes ranked chunk ids, gold ids, first gold rank when known, and formula score breakdown metadata

### Requirement: Formula gold quality can be judged
Paper RAG SHALL include formula QA samples in the gold quality loop so blind semantic formula gold can be kept, repaired, or routed to human review.

#### Scenario: Formula gold judge evaluates sample quality
- **WHEN** a blind semantic formula QA pair is audited
- **THEN** the system can record whether the question is clear, gold evidence supports the answer, required formula context is complete, equivalent gold is needed, and what repair action is suggested
- **AND** formula-specific bad gold reasons such as `formula_context_missing`, `question_ambiguous`, and `gold_chunk_not_supporting` are reportable
