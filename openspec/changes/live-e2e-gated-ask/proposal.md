## Why

The live RAG E2E workflow currently proves paper ingestion and retrieval against real Qdrant/Postgres services, but it does not exercise the gated answer path. A storage or filter regression can still leave production gated asks abstaining silently while the live workflow stays green.

## What Changes

- Add a live E2E test that runs `PaperRagApplicationService.rag_ask(generate=True)` after the live chunk pipeline indexes a paper.
- Use a local grounded answer worker in the test so live E2E does not require external LLM credentials.
- Assert that the gated payload includes a terminal status, transcript id, context pack, passages, answer candidate, gate results, and citations when answered.

## Capabilities

### New Capabilities
- `rag-live-e2e-gated-ask`: Live RAG E2E validates the gated ask closure over real live retrieval infrastructure.

### Modified Capabilities

## Impact

- Affects `tests/business/research/integration/test_chunk_paper_e2e.py`.
- No production runtime code changes are required.
