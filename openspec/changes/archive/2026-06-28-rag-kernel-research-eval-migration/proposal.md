## Why

`business/research/rag/evidence_eval.py` still owns generic retrieval metrics such as Hit@K, MRR, nDCG, evidence coverage, and source locator coverage. The RAG kernel already provides domain-neutral evaluation primitives, but Research cannot use them safely until the primitives support evidence candidates that map one retrieved item to multiple underlying chunk ids or source locators.

## What Changes

- Extend `framework/rag/evaluation/retrieval_metrics.py` to support ranked evidence id candidate groups and ranked source locator candidate groups.
- Preserve exact-match behavior for existing callers that only pass ranked ids and locators.
- Rewire Research evidence aggregation to use framework retrieval metrics for Hit@K, MRR, nDCG, evidence coverage, and source locator coverage.
- Keep paper-specific metrics in Research: required type coverage, image recall, visual evidence coverage, citation accuracy, overlap citation accuracy, and over-retrieval.
- Keep Paper benchmark output shape and evaluator behavior compatible.

## Capabilities

### New Capabilities

- `rag-kernel-candidate-aware-retrieval-metrics`: generic retrieval metrics can score retrieved evidence that represents multiple candidate evidence ids or source locators.

### Modified Capabilities

- `paper-rag-evaluation-kernel-migration`: Research evidence evaluation delegates generic retrieval metrics to `framework/rag/evaluation` while retaining paper-specific evaluation rules.

## Impact

Affected code is limited to framework retrieval metric utilities, Research evidence aggregation, targeted tests, and this OpenSpec change. No Research ranking, gold generation, visual parsing, answer evaluation, benchmark CLI behavior, or production artifact paths are changed.
