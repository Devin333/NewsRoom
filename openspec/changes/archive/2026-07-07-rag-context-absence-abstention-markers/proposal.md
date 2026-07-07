## Why

The real-corpus live answer eval exposed negative QA responses such as "does not state" and "contains no mention" that are semantically abstentions but were treated as ordinary answers by runtime and evaluation markers. That can regress abstention accuracy even when the gated path is correctly refusing unsupported claims.

## What Changes

- Expand context-absence abstention markers in the Paper answer worker.
- Align framework and Research answer evaluation markers with the runtime marker set.
- Add focused unit coverage for `does not state` and `contains no mention` variants.

## Capabilities

### New Capabilities

### Modified Capabilities
- `rag-live-answer-evaluation`: live answer evaluation and runtime answer normalization consistently classify common context-absence phrases as abstentions.

## Impact

- Affected runtime code: `business/research/rag/adapters/answer_worker.py`.
- Affected evaluation code: `business/research/rag/evaluation/paper_answer_eval.py`, `framework/rag/evaluation/answer_metrics.py`.
- Affected tests: `tests/business/research/rag/adapters/test_answer_worker.py`, `tests/business/research/rag/test_answer_eval.py`.
