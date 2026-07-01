## Why

Paper RAG retrieval is now strong enough for internal pilot usage, but real benchmark results show formula retrieval is the main remaining retrieval bottleneck. The latest blind semantic run has `formula_qa Hit@10 = 0.667`, `formula_qa MRR = 0.444`, `formula_explanation_qa Hit@10 = 0.667`, and `formula_explanation_qa evidence coverage@10 = 0.600`, while figure, citation, and table queries are materially stronger.

This change makes formulas first-class retrieval evidence instead of treating LaTeX as ordinary text, and closes the gold/judge quality loop that currently surfaces as `gold_audit_warning` and `blind_semantic_without_gold_judge` warnings.

## What Changes

- Add deterministic formula normalization that extracts stable LaTeX, symbols, operators, structure tokens, reference labels, and context terms.
- Add formula-specific sparse scoring and expose formula score components in candidate metadata.
- Add a named formula retrieval policy that improves formula query ranking without changing default retrieval behavior.
- Strengthen formula explanation graph expansion so formula chunks and explanation paragraphs are retrieved together.
- Add formula-specific failure diagnostics and benchmark summaries for `@3`, `@5`, `@10`, MRR, evidence coverage, and source locator coverage.
- Extend the existing gold quality loop so blind semantic formula gold can be judged, fixed, or routed for human review.
- Keep all new behavior policy-gated and offline-testable; no mandatory external formula embedding model is introduced in this change.

## Capabilities

### New Capabilities

- `paper-rag-formula-retrieval-quality`: Paper-specific formula retrieval, formula explanation graph expansion, formula diagnostics, and gold/judge quality behavior.

### Modified Capabilities

- `rag-kernel-candidate-aware-retrieval-metrics`: Retrieval reports must expose formula-focused diagnostics and preserve top-k evidence/source-locator reporting for formula QA slices.

## Impact

- Affected code:
  - `business/research/rag/retrieval/paper_retriever.py`
  - `business/research/rag/retrieval/paper_policy.py`
  - `business/research/rag/adapters/paper_field_text.py`
  - `business/research/rag/evaluation/paper_evidence_eval.py`
  - `business/research/rag/evaluation/paper_benchmark_suite.py`
  - Paper RAG retrieval/evaluation tests under `tests/business/research/rag/`
- New code:
  - Formula normalization and scoring helpers under `business/research/rag/retrieval/`
- No breaking changes to default retrieval policy.
- No new network dependency is required.
