## Why

The PRD calls for `framework/rag/context/nearby_context.py`. Research currently has generic logic for reading nearby context ids from metadata, parent ids, and `referenced_by_chunks`. The edge meanings remain Paper-specific, but collecting and deduplicating related context ids is domain-neutral.

## What Changes

- Add `framework/rag/context/nearby_context.py`.
- Introduce `collect_nearby_context_ids()` and `NearbyContextIds`.
- Rewire `AnswerContextAssembler` to use the kernel helper for related context id collection.
- Keep Paper-specific context expansion, store lookups, and expansion metadata in Research retrieval.
- Add framework unit tests for direct edges, parent ids, reference-list edges, custom edge keys, and deduplication.

## Capabilities

### New Capabilities

- `rag-kernel-nearby-context`: domain-neutral nearby context id collection from metadata and relation edges.

### Modified Capabilities

- `paper-rag-answer-context-nearby-migration`: Paper answer context selection delegates generic related-id extraction to the RAG kernel while preserving Paper context selection behavior.

## Impact

Affected code is limited to `framework/rag/context`, `business/research/rag/generator.py`, tests, and this OpenSpec change. Existing answer context ordering remains compatible.
