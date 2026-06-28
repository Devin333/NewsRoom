## Why

The core RAG DTOs now exist, but reusable retrieval scoring and context shaping still live in Research-specific code. We need domain-neutral scoring, deduplication, citation, and budget primitives before moving Paper RAG behavior out of `business/research/rag`.

## What Changes

- Add `framework/rag/retrieval` utilities for score fusion, field lexical scoring, evidence ordering, and deduplication.
- Add `framework/rag/context` utilities for context budget trimming, citation provenance resolution, and basic context assembly.
- Keep the new utilities additive and pure; do not rewire existing `ResearchRetriever` or benchmark behavior in this change.
- Add tests that define expected score breakdown, dedup, budget, and overlap citation behavior.

## Capabilities

### New Capabilities

- `rag-kernel-retrieval`: introduces domain-neutral retrieval scoring, field scoring, and dedup utilities for `RAGEvidence`.
- `rag-kernel-context`: introduces domain-neutral context budget, citation resolution, and context assembly utilities.

### Modified Capabilities

- None

## Impact

Affected code is limited to new `framework/rag/retrieval`, new `framework/rag/context`, and tests under `tests/framework/rag`. Existing Research retrieval, Harness RAG, CLI entrypoints, benchmark generation, and Paper artifact processing remain behaviorally unchanged.
