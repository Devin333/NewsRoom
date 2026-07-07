## Context

`ResearchRetriever._sparse_lexical_candidates` needs to scan all chunks for a paper so it can rank exact lexical and formula matches. Today that scan uses `_list_store_chunks`, which probes `list_chunks`, then `chunks`, then `_chunks` by reflection. This hides missing production contracts and can silently disable sparse recall for adapters that only implement vector search methods.

The production factory wires `ResearchRetriever` with `PaperChunkStoreAdapter(PaperChunkStore(qdrant_store_from_env()))`. The adapter currently implements search and lookup, but not `list_chunks`; only the relational repository adapter exposes list semantics. The fix should make the needed capability explicit at the business port and storage payload-store boundary before the larger PRD moves sparse recall into a proper BM25 index.

## Goals / Non-Goals

**Goals:**

- Make paper chunk listing an explicit `ChunkStorePort` requirement.
- Make the Qdrant-backed production adapter able to list chunks for a paper through its payload store.
- Remove private-attribute reflection from sparse retrieval.
- Keep current sparse lexical scoring behavior unchanged.
- Make missing inventory observable in retrieval metadata.

**Non-Goals:**

- Do not replace sparse lexical scoring with BM25 in this change.
- Do not refactor the whole retrieval pipeline into channel classes in this change.
- Do not change `RetrievalResult` or downstream answer generation contracts.

## Decisions

1. **List through the payload store, not the retriever.**
   - The storage-facing `ChunkPayloadStorePort` gains `list_paper_payloads(paper_id)`.
   - `PaperChunkStoreAdapter.list_chunks` converts those payloads into `PaperChunk`.
   - Rationale: business retrieval stays storage-agnostic and the Qdrant details remain in infrastructure.

2. **Use Qdrant scroll for paper-scoped listing.**
   - `PaperChunkStore.list_paper_payloads` delegates to a generic `QdrantVectorStore.list_payloads(collection, filters)`.
   - Rationale: this is the current production payload source for vector search, and it avoids fabricating a second authority inside the retriever.

3. **Remove reflection fallback instead of keeping it as compatibility glue.**
   - The retriever directly calls `self._store.list_chunks(paper_id)`.
   - Rationale: PRD 16 explicitly requires contracts to be visible and forbids silent reflection fallback.

4. **Expose sparse inventory degradation through result metadata.**
   - If sparse is enabled but chunk listing returns no chunks, retrieval metadata records a degradation entry.
   - Rationale: empty sparse recall can be legitimate for an empty paper, but production diagnostics must be able to see that sparse had no inventory.

## Risks / Trade-offs

- Qdrant scroll may be slower than a dedicated BM25 index for large papers -> This is a bridge fix; PRD S9 replaces scan-based sparse recall with an index.
- Listing all chunks from the vector store duplicates repository listing capability -> The current production retriever is wired to the vector store, so the explicit vector payload listing keeps behavior live until a repository-backed or indexed sparse channel is introduced.
- Existing fake/scripted tests may rely on `.chunks` reflection -> Tests should implement `list_chunks` explicitly, matching the new port contract.

## Migration Plan

1. Add explicit port methods and infrastructure listing support.
2. Update retriever sparse and formula reverse-context scans to call the port directly.
3. Update tests/fakes that are intended to satisfy `ChunkStorePort`.
4. Validate with targeted retrieval/storage tests and OpenSpec strict validation.
