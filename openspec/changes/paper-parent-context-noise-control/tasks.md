## 1. Retrieval Design

- [x] 1.1 Define parent expansion policy fields for count, token, snippet, rerank, and intent-specific budgets.
- [x] 1.2 Specify parent metadata required for traceability and downstream evidence inspection.

## 2. Implementation

- [x] 2.1 Replace unbounded parent expansion with budgeted parent candidate assembly.
- [x] 2.2 Add long-parent child-anchored snippet extraction.
- [x] 2.3 Add optional parent reranking with deterministic fallback.
- [x] 2.4 Apply intent-specific parent budgets.
- [x] 2.5 Expose parent expansion metadata through evidence candidates.

## 3. Tests

- [x] 3.1 Unit test: parent count budget limits returned parent chunks.
- [x] 3.2 Unit test: long parent is returned as a child-anchored snippet with source metadata.
- [x] 3.3 Unit test: parent reranker orders and filters parent candidates.
- [x] 3.4 Unit test: table/factual intent uses tighter parent budget than method intent.
- [x] 3.5 Regression test: no-parent fallback still returns children.

## 4. Verification

- [x] 4.1 Run focused research RAG tests.
- [x] 4.2 Run compile check.
- [x] 4.3 Validate OpenSpec strict.
