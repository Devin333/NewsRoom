## Context

The RAG runtime path now persists gated ask transcripts and exposes replay tooling, but persistence currently happens inline after the RAG session finishes. A filesystem error in that audit path can fail the entire `rag_ask` request even though the answer was already produced. Separately, interface documentation tests require stable docs for SDK, web console, and MCP behavior, but those files are missing from the tree.

## Goals / Non-Goals

**Goals:**
- Restore the required interface documentation files with operationally useful content.
- Document MCP confirmation metadata for dangerous external-write tools.
- Keep transcript persistence as an audit side effect that cannot fail a successful gated ask response.
- Preserve a visible `transcript_artifact` payload for both successful and failed persistence.

**Non-Goals:**
- Add database-backed transcript persistence.
- Change the RAG transcript envelope schema.
- Run a real external LLM live eval or configure GitHub secrets.
- Refactor the evidence-eval CLI/core boundary.

## Decisions

1. Treat transcript persistence as best-effort in `PaperRagApplicationService`.
   - Rationale: the service owns the interface payload and is the narrowest point that can preserve the answer while reporting audit storage failure.
   - Alternative: catch errors inside `PaperRagTranscriptFileStore`. Rejected because callers that need strict persistence, such as replay setup tests, should still receive store errors directly.

2. Return an additive error payload in `transcript_artifact` on persistence failure.
   - Rationale: callers already look at `transcript_artifact`; keeping the field present avoids inventing a second reporting channel.
   - Alternative: set `transcript_artifact` to `None`. Rejected because it hides the difference between disabled persistence and failed persistence.

3. Restore docs with focused operational examples rather than placeholder stubs.
   - Rationale: the docs are part of the interface contract and should explain supported surfaces that tests and operators rely on.

## Risks / Trade-offs

- [Risk] A failed transcript write can be missed by operators if only returned in the payload. -> Mitigation: include an explicit `error` object in `transcript_artifact` and cover it with a service test.
- [Risk] Documentation can drift from implementation. -> Mitigation: keep the existing docs contract tests and include MCP confirmation metadata required by the live MCP surface.
