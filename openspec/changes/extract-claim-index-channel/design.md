## Context

Citation query recall uses `PaperClaimSearchPort.search_claims`, then merges claim metadata into chunks and optionally includes claim rankings in hybrid RRF. These steps are source-specific channel behavior and can move out of the retriever without changing query planning or downstream scoring.

## Goals / Non-Goals

**Goals:**

- Move claim search, claim hit merge, and claim hit ranking into a channel class.
- Preserve current warning-and-empty behavior when the claim index fails.
- Preserve `claim_index_*` metadata fields used by downstream scoring and evidence reports.

**Non-Goals:**

- Do not change when claim recall is enabled; `ResearchRetriever` still gates it by citation intent.
- Do not change claim score weights or hybrid RRF behavior.
- Do not extract field embedding or visual channel logic in this slice.

## Decisions

- **Channel owns metadata merge:** Claim-specific metadata shape belongs with the claim channel, so `_merge_claim_index_hit` moves out of `paper_retriever.py`.
- **Chunk-store dependency:** The channel receives `ChunkStorePort` so it can turn claim hits into ranked chunk candidates for current hybrid fusion.

## Risks / Trade-offs

- The channel still exposes compatibility methods returning `PaperChunk` tuples. This is temporary until the full pipeline uses `RankedHit` end to end.
