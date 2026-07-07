# paper-rag-retrieval-query-planner Specification

## Purpose
TBD - created by archiving change extract-query-planner-plan. Update Purpose after archive.
## Requirements
### Requirement: Retrieval request produces a serializable plan
Paper RAG retrieval SHALL convert each retrieval request into a serializable `RetrievalPlan` before recall execution.

#### Scenario: Plan captures route and filters
- **WHEN** a retrieval request is planned
- **THEN** the plan includes the primary intent, recall routes, base filters, candidate filter groups, candidate limit, and element query labels

### Requirement: Planner preserves existing filter behavior
The query planner MUST preserve the existing route and candidate-filter behavior for formula, figure, table, numerical-result, comparison, citation, contribution, and concept-method queries.

#### Scenario: Formula sparse policy uses formula chunks
- **WHEN** the policy enables formula sparse retrieval and the question routes to `formula_query`
- **THEN** the plan uses `{"chunk_type": "formula"}` as the candidate filter group

#### Scenario: Route candidate groups are expanded
- **WHEN** a route defines candidate filter groups
- **THEN** the plan combines route base filters with each candidate filter group and deduplicates equivalent filters

### Requirement: Planner preserves current overfetch behavior
The query planner MUST preserve current candidate-limit overfetch behavior.

#### Scenario: Element labels increase candidate limit
- **WHEN** a question contains an element label such as an equation, table, or figure reference
- **THEN** the candidate limit is at least `request.limit * element_label_overfetch_multiplier`

#### Scenario: Citation queries increase candidate limit
- **WHEN** a question routes to `citation_query`
- **THEN** the candidate limit is at least `request.limit * citation_claim_overfetch_multiplier`
