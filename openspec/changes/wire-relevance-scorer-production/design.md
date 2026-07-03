## Design

Production Paper RAG keeps relevance verification deterministic by adapting the
existing reranker into `RelevanceScorerPort` instead of introducing a new model
path. `RerankerRelevanceScorer` normalizes reranker outputs before they enter
`SourceVerifier`, so the framework gate can compare evidence candidates against
stable source-policy thresholds.

`PaperRAGSession` accepts the scorer as an optional dependency and only builds a
custom `SourceVerifier` when that dependency is present. The interface factory is
the production composition root: when reranking is enabled it reuses the same
reranker instance for retrieval reranking and source relevance scoring; when
reranking is disabled, relevance scoring remains disabled.

Research source policies declare a default `min_relevance` plus
`min_relevance_by_type` overrides. Formula and table evidence can use relaxed
thresholds while other evidence keeps the stricter default. `SourceVerifier`
resolves the effective threshold per candidate evidence type and preserves the
existing no-scorer behavior for callers that do not configure relevance scoring.
