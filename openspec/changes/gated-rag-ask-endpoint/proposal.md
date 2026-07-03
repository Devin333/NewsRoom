## Why

The chunk-based paper `/rag-ask` path can generate an answer by calling `AnswerGenerator` directly after retrieval, bypassing the bounded Harness RAG answer gate. That means generated answers and citations are not represented as deterministic `ANSWERED` or `ABSTAINED` session outcomes.

## What Changes

- Add an optional gated generation path to `PaperRagApplicationService.rag_ask`.
- Wire `PaperRAGSession` with the existing `PaperAnswerWorker` adapter when gated generation is requested.
- Build ask-specific `ResearchRetrievalGoal` values from paper id, question, and query intent.
- Return gated answer status, claims, citations, gate results, and transcript id in the service/API payload.
- Keep retrieve-only behavior unchanged, and keep an explicit non-gated fallback for compatibility.

## Capabilities

### New Capabilities
- `gated-rag-ask-endpoint`: Chunk-based paper ask can return deterministic gated answer outcomes.

### Modified Capabilities

## Impact

- Affected interfaces: `interfaces/services/paper_rag_service.py`, `interfaces/api/routers/research.py`, `interfaces/cli/commands/paper.py`.
- Affected composition root: `interfaces/services/paper_rag_factory.py`.
- Affected business modules: `business/research/application/paper_rag_session.py`, `business/research/application/ask_paper.py`, `business/research/services/rag_policy.py`.
- Existing `generate=False` calls remain retrieve-only and compatible.
