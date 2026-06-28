## Why

The RAG kernel contracts and adapter utilities now exist, but `business/research/rag/retrieval_port.py` still hand-builds Paper evidence metadata inline. That keeps generic kernel metadata out of the live Harness retrieval path and leaves the Paper port responsible for a large mapping that belongs at the Research adapter boundary.

## What Changes

- Add a Research-owned metadata projection helper that maps `PaperChunk` evidence metadata into the existing `EvidencePack` shape.
- Preserve every existing Paper metadata key currently returned by `PaperChunkRetrievalPort`.
- Add kernel evidence metadata keys, including `rag_document_id`, `rag_chunk_id`, `rag_score`, `rag_score_breakdown`, and `rag_source_locator`.
- Rewire `PaperChunkRetrievalPort` to call the adapter helper instead of maintaining its own inline metadata mapping.
- Keep `ResearchRetriever` ranking, chunk ordering, benchmark behavior, and Harness retrieval contracts unchanged.

## Capabilities

### New Capabilities

- `paper-rag-kernel-migration`: exposes RAG kernel evidence metadata through the existing Paper retrieval port while keeping Paper-specific projection inside Research.

### Modified Capabilities

- `paper-rag-kernel-adapter`: extends the adapter boundary so Paper evidence metadata is projected from a single Research-owned helper.

## Impact

Affected code is limited to `business/research/rag/adapters`, `business/research/rag/retrieval_port.py`, targeted Research RAG tests, and this OpenSpec change. The generic `framework/rag` package remains domain-neutral and does not import Research code.
