## Why

The framework RAG loop already supports deterministic relevance verification through
`SourceVerifier(relevance_scorer=...)`, but the production paper RAG composition root
does not configure a scorer. As a result, the `rag_relevance` gate is not active in
the default gated paper ask path.

## What Changes

- Add a business adapter that turns the existing `RerankerPort` into a framework
  `RelevanceScorerPort`.
- Wire the relevance scorer into `PaperRAGSession` and the paper RAG factory when
  reranking is enabled.
- Add source-policy relevance thresholds, including relaxed thresholds for table
  and formula evidence.
- Support evidence-type-specific relevance thresholds in `SourceVerifier`.

## Capabilities

### New Capabilities
- `paper-rag-production-relevance-scorer`: Production paper RAG sessions can reject
  low-relevance evidence through the existing deterministic relevance gate.

## Impact

- Affected business modules: paper RAG session assembly, research policy builder,
  and a new relevance scorer adapter.
- Affected framework modules: typed threshold handling in source verification.
- Affected interface modules: paper RAG composition root.
- Affected tests: adapter, factory, session, and source verifier regressions.
