## MODIFIED Requirements

### Requirement: Paper routing uses kernel rule matching
Research routing SHALL use the kernel query intent matcher while keeping Paper-specific routing semantics in Research.

#### Scenario: Paper route behavior is preserved
- **WHEN** Research classifies figure, table, formula, result, comparison, contribution, or method questions
- **THEN** generic rule matching is performed by `framework/rag/retrieval`
- **AND** Paper-specific intent names, filters, section role filters, propositions, and route construction remain Research-owned

#### Scenario: Live-answer evaluation questions use result-aware routes
- **WHEN** a Paper question asks about evaluation, experiments, results, user studies, benchmarks, appendix result details, dataset splits, prompt comparisons, or win-rate judgments
- **THEN** Research classifies the question as a result-aware Paper intent such as `numerical_result` or `comparison`
- **AND** the retrieval route includes result/table/conclusion or comparison/table context rather than only `method_body`

#### Scenario: Specialized element routes keep precedence
- **WHEN** a Paper question explicitly targets a citation, figure, table, or formula
- **THEN** the specialized Paper route keeps precedence over broad result/evaluation wording
