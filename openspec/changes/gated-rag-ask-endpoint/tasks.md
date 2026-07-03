## 1. Session And Policy Wiring

- [x] 1.1 Add generation policy support to Research RAG session spec building.
- [x] 1.2 Let `PaperRAGSession` inject an optional answer worker into `BoundedRAGSessionController`.
- [x] 1.3 Let `paper_rag_factory.build_paper_rag_session` construct a `PaperAnswerWorker` on request.

## 2. Ask Goal Construction

- [x] 2.1 Extend `AskPaperUseCase` with deterministic paper ask goal construction.
- [x] 2.2 Map query intent to required evidence types and allowed source refs.

## 3. Service/API/CLI

- [x] 3.1 Add `gated` option to `PaperRagApplicationService.rag_ask`.
- [x] 3.2 Route `generate=True, gated=True` through `PaperRAGSession`.
- [x] 3.3 Return status, answer, claims, citations, gate results, transcript id, and context pack summary.
- [x] 3.4 Add API and CLI flags for gated fallback control while keeping default gated generation.

## 4. Tests

- [x] 4.1 Add business/session wiring tests.
- [x] 4.2 Add ask goal construction tests.
- [x] 4.3 Add service tests for retrieve-only, gated generated, abstained, and legacy fallback payloads.

## 5. Validation

- [x] 5.1 Run targeted business/interface tests.
- [x] 5.2 Run compile and strict OpenSpec validation.
- [x] 5.3 Commit the completed T5 slice.
