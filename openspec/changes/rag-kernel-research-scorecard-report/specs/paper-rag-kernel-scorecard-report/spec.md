## ADDED Requirements

### Requirement: Research reports expose generic RAG scorecards
Research evidence regression reports SHALL expose a generic `RAGEvaluationReport` payload in addition to existing Paper-specific report fields.

#### Scenario: Report dictionary includes a scorecard
- **WHEN** `EvidenceRegressionReport.to_dict()` is called
- **THEN** the payload includes `rag_evaluation_report`
- **AND** the nested scorecard contains `MetricValue` entries for retrieval, answer, and generation metrics when those result types are present

### Requirement: Paper-specific report compatibility is preserved
The scorecard integration SHALL NOT remove or rename existing Research report fields.

#### Scenario: Existing report consumers read Paper metrics
- **WHEN** the regression report is serialized
- **THEN** existing `retrieval`, `answer`, `generation`, `ab`, `thresholds`, `passed`, and `issues` fields remain available
- **AND** existing threshold issue calculation remains unchanged

### Requirement: Paper-specific metrics remain Research-owned
Paper-specific metrics SHALL remain in Research code and may be attached to the generic scorecard only as metadata.

#### Scenario: Paper metrics are attached as metadata
- **WHEN** retrieval results include type, image, visual, citation, overlap, or over-retrieval metrics
- **THEN** those values are preserved under scorecard metadata
- **AND** framework evaluation code does not import Research models or Paper-specific evaluators

### Requirement: Research answer failures map to generic failure taxonomy
Known Research answer failure reasons SHALL map to generic `RAGFailureReason` values when a safe mapping exists.

#### Scenario: Missing context failure is mapped
- **WHEN** answer evaluation reports `missing_gold_in_llm_context`
- **THEN** the generic scorecard reports `context_missing_gold`
- **AND** the raw Research failure reason counts remain available in scorecard metadata
