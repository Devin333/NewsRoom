## Why

PRD 16 targets homogeneous recall channels and removal of source-specific merge/ranking logic from `paper_retriever.py`. Dense and sparse recall are now channels; claim index recall still has search, merge, and RRF ranking logic inline in the retriever.

## What Changes

- Add `ClaimIndexChannel` under `business.research.rag.retrieval.channels`.
- Move claim index search error handling, claim metadata merge, and claim ranking conversion into the channel.
- Delegate claim search, candidate merge, and hybrid RRF claim ranking from `ResearchRetriever`.
- Add focused channel tests.

## Capabilities

### New Capabilities

- `paper-rag-claim-index-channel`: Claim index recall is implemented as a reusable recall channel.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/rag/retrieval/channels/claim_index.py`
  - `business/research/rag/retrieval/paper_retriever.py`
  - retrieval channel tests
- No intended behavior change to citation query recall or claim metadata.
