## 1. Framework Answer Model And Gate

- [x] 1.1 Add `AnswerClaim`, `GroundedAnswerCandidate`, `RAGSessionStatus.ANSWERED`, `RAGSessionStatus.ABSTAINED`, and `RAGSessionResult.answer`.
- [x] 1.2 Add `AnswerWorkerPort`.
- [x] 1.3 Add `RAGAnswerGate` deterministic checks and exports.

## 2. Optional Generation Phase

- [x] 2.1 Add `generation_policy` to `RAGSessionSpec` and `RAGExecutionPolicy`.
- [x] 2.2 Extend `BoundedRAGSessionController` with optional answer worker/gate injection.
- [x] 2.3 Run generation only when enabled and return `ANSWERED`/`ABSTAINED` through deterministic gate results.

## 3. Research Adapter

- [x] 3.1 Add `PaperAnswerWorker` adapter around existing `AnswerGenerator`.
- [x] 3.2 Preserve safe abstention when context pack lacks Paper chunk metadata.

## 4. Tests

- [x] 4.1 Add framework answer gate tests.
- [x] 4.2 Add framework generation phase tests for disabled, answered, invalid, and abstained outcomes.
- [x] 4.3 Add Research Paper answer worker adapter tests.

## 5. Validation

- [x] 5.1 Run targeted framework and Research tests.
- [x] 5.2 Run compile and strict OpenSpec validation.
- [x] 5.3 Commit the completed T4 slice.
