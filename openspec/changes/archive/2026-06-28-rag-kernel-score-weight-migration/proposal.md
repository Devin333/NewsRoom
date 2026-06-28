## Why

Research retrieval still owns generic score-weight normalization and weighted component summation inside `ResearchRetriever`. These operations are not paper-specific: they apply to child scoring, parent scoring, field scoring, and future non-Research RAG policies. Moving them into `framework/rag/retrieval` advances the V3 retrieval scoring migration without changing Paper-specific ranking policy.

## What Changes

- Add generic `normalize_score_weights()` to `framework/rag/retrieval/scoring.py`.
- Add generic `weighted_component_score()` to `framework/rag/retrieval/scoring.py`.
- Rewire `ResearchRetriever` to use these kernel primitives for field, child, and parent score composition.
- Keep Research-owned field extraction, intent policy, section heading scoring, graph scoring, element label matching, visual fusion, reranking, and expansion behavior unchanged.
- Add framework unit tests for weight normalization and weighted component scoring.

## Capabilities

### New Capabilities

- `rag-kernel-score-weighting`: domain-neutral score weight normalization and weighted component scoring.

### Modified Capabilities

- `paper-rag-retrieval-score-migration`: Paper retrieval uses kernel score-weight primitives while retaining Paper-specific scoring policy and metadata.

## Impact

Affected code is limited to `framework/rag/retrieval`, `business/research/rag/retriever.py`, scoring tests, and this OpenSpec change. The expected retrieval ordering and benchmark behavior remain unchanged for equivalent inputs.
