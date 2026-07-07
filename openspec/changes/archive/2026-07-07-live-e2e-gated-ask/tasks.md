## 1. Specification

- [x] 1.1 Validate the OpenSpec change artifacts.

## 2. Live E2E Test

- [x] 2.1 Add a deterministic grounded answer worker for the live gated ask E2E.
- [x] 2.2 Build a `PaperRAGSession` over the live chunk store and call `PaperRagApplicationService.rag_ask(generate=True)`.
- [x] 2.3 Assert terminal status, transcript, context pack, passages, answer candidate, gate results, and citations.

## 3. Verification

- [x] 3.1 Run the targeted live E2E test in the local non-live environment and confirm it remains skipped unless opt-in env is configured.
- [x] 3.2 Run OpenSpec validation and compile checks.
