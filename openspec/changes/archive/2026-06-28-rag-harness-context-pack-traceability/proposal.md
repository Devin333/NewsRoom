## Why

The RAG kernel decoupling PRD requires `RAGContextPack` accepted evidence to retain source refs, span refs, and artifact refs, and requires Harness transcripts to make accepted/rejected evidence traceable. `EvidenceCandidate` already carries source and span refs, but artifact refs and a pack-level evidence trace were not explicit.

## What Changes

- Add optional `artifact_refs` to `EvidenceCandidate`.
- Add `artifact_refs` and `evidence_trace` to `RAGContextPack`.
- Preserve artifact refs from kernel `RAGEvidence` metadata and retrieval request artifacts.
- Include evidence trace and artifact refs in context envelope metadata.
- Keep session routing, gates, retrieval scoring, and Research behavior unchanged.

## Capabilities

### New Capabilities

- `rag-context-pack-evidence-traceability`: context packs expose source, span, artifact, lineage, confidence, and score trace rows for accepted/rejected/conflicting evidence.

### Modified Capabilities

- `rag-harness-kernel-evidence-adapter`: kernel evidence conversion preserves artifact refs when present in metadata.

## Impact

Affected code is limited to Harness RAG models, context pack assembly, session artifact propagation, kernel evidence adapter, focused tests, and this OpenSpec change. No paper-specific logic is added to Harness or the RAG kernel.
