## Why

Research answer evaluation still owns deterministic fact matching, citation grounding, source locator grounding, abstention detection, and answer failure reason logic. These rules are not Paper-specific; only the mapping from `EvidenceQAPair` into an answer metric case is Research-specific.

## What Changes

- Extend `framework/rag/evaluation/answer_metrics.py` with a reusable answer scoring DTO and scorer.
- Preserve existing `AnswerMetricCase`, `evaluate_answer_case()`, and simple metric helpers.
- Rewire Research `EvidenceAnswerEvaluator` to project `EvidenceAnswerSample` into the kernel answer metric case.
- Keep Research-specific `EvidenceQAPair`, `EvidenceAnswerScores`, `qa_type` grouping, benchmark report shape, and Paper failure string compatibility.

## Capabilities

### New Capabilities

- `rag-kernel-answer-eval-scoring`: domain-neutral deterministic answer-level scoring for fact coverage, citation grounding, source locator grounding, abstention, context coverage, and failure reason.

### Modified Capabilities

- `paper-rag-answer-eval-kernel-wiring`: Paper answer evaluation delegates generic scoring to the RAG kernel while preserving Paper-facing benchmark output.

## Impact

Affected code is limited to `framework/rag/evaluation/answer_metrics.py`, Research answer evaluation wiring, focused tests, and this OpenSpec change. No retrieval policy, benchmark gold generation, or report schema changes are intended.
