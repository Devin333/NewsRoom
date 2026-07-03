## Context

`ResearchRetriever` currently handles dense, sparse, field embedding, claim, and visual recall directly. The PRD target is a retrieval pipeline where all recall sources return the same hit shape and fusion happens once. This change starts that migration by creating stable primitives and moving RRF fusion out of the retriever.

## Goals / Non-Goals

**Goals:**

- Establish the ranked hit/channel protocol used by later channel extraction.
- Make RRF fusion deterministic and independently tested.
- Preserve current `ResearchRetriever` output and metadata.

**Non-Goals:**

- Do not extract all channels in this slice.
- Do not change ranking weights or tuned policy values.
- Do not introduce YAML policy loading yet.

## Decisions

- **Chunk id first:** `RankedHit` stores `chunk_id`, score, channel, and metadata. Existing code can still carry `PaperChunk` until later migration, but the target shape is chunk-id based.
- **Compatibility helper:** `fuse_ranked_hits` works on `RankedHit`; `fuse_chunk_rankings` adapts the current `list[tuple[PaperChunk, score]]` shape so existing retriever behavior stays unchanged.
- **RRF only for this slice:** Weighted fusion will be added when channel extraction makes all inputs homogeneous.

## Risks / Trade-offs

- **Partial migration still leaves `paper_retriever.py` large** -> This is intentional; later slices move individual channels once the contract is in place.
- **Duplicate fusion helpers during transition** -> The old private helper delegates to the new module, so the actual algorithm has one implementation.
