## 1. Transcript Store

- [x] 1.1 Add an interface-layer file store for Paper RAG transcript envelopes.
- [x] 1.2 Support deterministic artifact paths and load-by-id/load-by-path behavior.

## 2. Service Wiring

- [x] 2.1 Inject the transcript store into `PaperRagApplicationService`.
- [x] 2.2 Persist gated `rag_ask` transcripts and return a `transcript_artifact` payload.
- [x] 2.3 Preserve retrieve-only payload behavior without writing transcripts.

## 3. Replay Command

- [x] 3.1 Add `python -m scripts.dev replay-rag <transcript-id-or-path>`.
- [x] 3.2 Print deterministic replay reports as JSON and return non-zero for non-replayable transcripts.

## 4. Tests and Validation

- [x] 4.1 Add service/store tests for persist, load-by-id, load-by-path, and retrieve-only no-op behavior.
- [x] 4.2 Add `scripts.dev` parser/command tests for replay-rag.
- [x] 4.3 Run targeted service, CLI, architecture, compile, and OpenSpec validation checks.
