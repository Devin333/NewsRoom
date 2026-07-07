## Why

`SourceVerifier` currently accepts evidence based on source confidence and lineage only. A retrieval round can therefore pass sources that are well-formed but do not answer the original question, leaving the Agentic RAG loop without a deterministic "is this evidence relevant?" signal.

## What Changes

- Add a framework-level `RelevanceScorerPort` and `RAGRelevanceGate`.
- Extend `SourceVerifier` so an injected scorer can reject low-relevance evidence with a structured `low_relevance` reason.
- Pass the original session question into source verification instead of scoring against rewritten retrieval queries.
- Add `rejection_summary` to the session gap report so later replanning can see why evidence was rejected.
- Preserve current behavior when no relevance scorer is configured.

## Capabilities

### New Capabilities
- `rag-source-relevance-verification`: Deterministic source relevance verification for Harness RAG evidence.

### Modified Capabilities

## Impact

- Affected framework modules: new `framework/harness/rag/relevance.py`, updated `source_verifier.py`, `session.py`, and `__init__.py`.
- Affected tests: new source relevance gate/verifier coverage and session gap report regression tests.
- No new external dependencies in this slice; business reranker wiring is left for a later T2 extension/production assembly slice.
