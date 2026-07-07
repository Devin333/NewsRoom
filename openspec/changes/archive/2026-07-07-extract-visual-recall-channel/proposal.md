## Why

PRD 16 targets five homogeneous recall channels. Dense, sparse, field embedding, and claim index recall are now channels; visual recall still performs search, hit deduplication, visual ranking conversion, and visual/text fusion setup inline in `paper_retriever.py`.

## What Changes

- Add `VisualRecallChannel` under `business.research.rag.retrieval.channels`.
- Move visual search, visual hit deduplication, visual hit ranking, and text/image score fusion into the channel.
- Delegate visual search, hybrid RRF visual ranking, and visual fusion from `ResearchRetriever`.
- Add focused visual channel tests.

## Capabilities

### New Capabilities

- `paper-rag-visual-recall-channel`: Visual recall is implemented as a reusable recall channel.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/rag/retrieval/channels/visual.py`
  - `business/research/rag/retrieval/paper_retriever.py`
  - retrieval channel tests
- No intended behavior change to visual search, fusion weights, or metadata.
