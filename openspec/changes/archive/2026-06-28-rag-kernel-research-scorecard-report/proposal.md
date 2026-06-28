## Why

Research evidence reports still serialize Paper-specific retrieval and answer metrics directly, while `framework/rag/evaluation` already provides `MetricValue`, `RAGScorecard`, and `RAGEvaluationReport`. To continue the V4 evaluation migration without weakening Research's paper-specific answer checks, the report layer should project existing Research metrics into the generic scorecard contract.

## What Changes

- Add a Research-owned scorecard adapter that maps `EvidenceEvalResult`, `EvidenceAnswerEvalResult`, and `GenerationEvalResult` into `RAGScorecard`.
- Include generic retrieval, answer, and generation metrics in the scorecard while preserving paper-specific retrieval metrics in scorecard metadata.
- Map Research answer failure reasons to the generic `RAGFailureReason` taxonomy where a safe mapping exists.
- Add `rag_evaluation_report` to `EvidenceRegressionReport.to_dict()` and render a RAG Scorecard section in markdown.
- Keep existing Research report fields, thresholds, markdown sections, benchmark CLI behavior, and paper-specific metrics unchanged.

## Capabilities

### New Capabilities

- `paper-rag-kernel-scorecard-report`: Research evidence regression reports can emit generic RAG scorecards and reports.

### Modified Capabilities

- None

## Impact

Affected code is limited to a Research adapter, `business/research/rag/evaluation_report.py`, report tests, and this OpenSpec change. Framework code remains domain-neutral and does not import Research.
