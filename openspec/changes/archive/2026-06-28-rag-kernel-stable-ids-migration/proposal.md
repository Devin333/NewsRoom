## Why

The PRD calls for `framework/rag/core/ids.py`. Research already stabilizes paper chunk ids using semantic keys, normalized content hashes, and a chunk manifest, but the core id and semantic-key helpers still live in Research/business utility code. Stable RAG ids are domain-neutral and should be available to future RAG adapters without importing Paper-specific modules.

## What Changes

- Add `framework/rag/core/ids.py`.
- Introduce `build_rag_stable_id()`, `normalize_semantic_text()`, `content_fingerprint()`, and `build_chunk_semantic_key()`.
- Rewire Research chunker, chunk manifest, page visual chunks, and fixed-window baseline to use the RAG kernel id helpers.
- Keep chunk manifest storage, Paper chunk remapping, source locator choice, and Paper-specific metadata in Research.
- Add framework unit tests for stable ids, content fingerprints, and semantic-key parts.

## Capabilities

### New Capabilities

- `rag-kernel-stable-ids`: domain-neutral stable id, content fingerprint, and chunk semantic key helpers.

### Modified Capabilities

- `paper-rag-stable-id-migration`: Paper chunking and benchmark helper ids delegate generic id/semantic-key construction to the RAG kernel while preserving Paper-specific manifest behavior.

## Impact

Affected code is limited to `framework/rag/core`, Research RAG/document id call sites, tests, and this OpenSpec change. Existing Paper chunk ids and semantic keys remain stable for equivalent inputs.
