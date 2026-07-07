## Why

The enterprise RAG review asks the evaluation failure taxonomy to distinguish expected-answer samples that over-abstain from samples that should abstain but answer incorrectly. Today the benchmark taxonomy collapses abstention failures under `abstention_wrong`, making it harder to measure whether supplemental retrieval and answer gates reduce over-conservative behavior.

## What Changes

- Add a distinct `abstained_over_conservative` failure reason for answerable samples that return an abstention.
- Preserve `abstention_wrong` for expected-abstain samples that produce a non-abstention answer.
- Include the new reason in benchmark fix manifests, failure reason counts, and scorecard/report outputs.
- Add focused regression tests for both taxonomy branches.

## Capabilities

### New Capabilities
- `rag-abstention-failure-taxonomy`: RAG evaluation reports distinguish over-conservative abstention from incorrect non-abstention behavior.

### Modified Capabilities

## Impact

- Affected code: `business/research/rag/evaluation/`.
- Affected tests: RAG benchmark/evaluation report tests under `tests/business/research/rag/`.
- No API, storage, dependency, or runtime-serving changes.
