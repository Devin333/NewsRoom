## 1. Framework contract and gate

- [x] 1.1 Add claim-level `span_refs` to `AnswerClaim` serialization and dict construction.
- [x] 1.2 Add deterministic `rag_answer_span_citation_integrity` checks to `RAGAnswerGate`.

## 2. Paper RAG integration

- [x] 2.1 Attach verified evidence span refs to `PaperAnswerWorker` claims.
- [x] 2.2 Expose answer-claim span refs in Paper RAG gated citation payloads.

## 3. Verification

- [x] 3.1 Add framework tests for valid, missing, unknown, mismatched, and abstention span citations.
- [x] 3.2 Update Paper RAG worker and service tests for claim and citation spans.
- [x] 3.3 Run targeted tests, OpenSpec strict validation, compile, smoke, and diff checks.
