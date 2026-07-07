## Context

`scripts.dev test-rag-live-e2e` runs `tests/business/research/integration/test_chunk_paper_e2e.py` under opt-in live environment variables. The existing tests index a real paper through Qdrant/Postgres and verify chunk retrieval, but no `rag_ask(generate=True)` path is exercised.

## Goals / Non-Goals

**Goals:**
- Reuse the existing live pipeline fixture and live `PaperChunkStoreAdapter`.
- Build a `PaperRAGSession` over the live chunk store.
- Inject a deterministic grounded answer worker that cites accepted evidence and span refs from the real context pack.
- Verify gated payload shape and transcript/event closure.

**Non-Goals:**
- Do not call a real external LLM in the live E2E workflow.
- Do not validate model answer quality in this slice; that is covered by live answer eval.
- Do not add a separate workflow job.

## Decisions

- Keep the test inside `test_chunk_paper_e2e.py`.
  - Rationale: `scripts.dev test-rag-live-e2e` already targets this file and owns the opt-in skip guard.
- Use a local answer worker instead of `PaperAnswerWorker`.
  - Rationale: the goal is gated closure over live retrieval infra, not external model availability.
- Assert payload invariants rather than exact answer text.
  - Rationale: retrieval ranking can vary across embeddings, but a valid gated answer payload has stable structural requirements.

## Risks / Trade-offs

- The stub worker can only prove gate wiring, not LLM quality. Mitigation: the separate live answer eval mode measures generated-answer behavior when real credentials are available.
- The test depends on live Qdrant/Postgres availability. Mitigation: it inherits the existing opt-in skip conditions and scheduled workflow service containers.
