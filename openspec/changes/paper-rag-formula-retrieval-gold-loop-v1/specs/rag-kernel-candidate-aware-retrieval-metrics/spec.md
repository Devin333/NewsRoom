## ADDED Requirements

### Requirement: Retrieval reports expose formula slice diagnostics
Research retrieval reports SHALL preserve generic top-k retrieval metrics while also exposing formula-slice diagnostics needed to evaluate formula QA quality.

#### Scenario: Formula slice metrics are reported
- **WHEN** Paper RAG benchmark reporting includes formula QA samples
- **THEN** the report includes `Hit@3`, `Hit@5`, `Hit@10`, MRR, evidence coverage, equivalent evidence coverage, and source locator coverage for formula QA and formula explanation QA slices
- **AND** these values are derived from the same candidate-aware retrieval metric semantics used by the broader benchmark

#### Scenario: Formula score components are observable
- **WHEN** a retrieved formula candidate includes formula sparse, field, graph, rerank, or label score metadata
- **THEN** benchmark diagnostics can summarize those components without changing the domain-neutral kernel metric calculations
