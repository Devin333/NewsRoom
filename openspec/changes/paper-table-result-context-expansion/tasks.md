## 1. Retrieval Design

- [x] 1.1 Audit current `ResearchRetriever` evidence assembly and query intent routing for table/result questions.
- [x] 1.2 Define a bounded table context expansion policy with per-table and global budgets.
- [x] 1.3 Decide which intents trigger expansion: `table_query`, `numerical_result`, `comparison`, and result-style questions.

## 2. Implementation

- [x] 2.1 Add a retrieval helper that expands table chunks through `nearby_context_chunk_id`, `referenced_by_chunks`, `parent_chunk_id`, and `parent_table_chunk_id`.
- [x] 2.2 Add role/title-prioritized result context selection for experiment, analysis, result, ablation, evaluation, and conclusion sections.
- [x] 2.3 Deduplicate expanded chunks and annotate expansion metadata.
- [x] 2.4 Preserve existing text/image fusion scoring and do not change parser output.

## 3. Tests

- [x] 3.1 Unit test: table chunk hit expands to nearby context and explicit referencing paragraph.
- [x] 3.2 Unit test: row-group table hit expands to parent table chunk.
- [x] 3.3 Unit test: result/conclusion paragraph is included only within budget and same paper.
- [x] 3.4 Unit test: missing referenced chunk is skipped without failure.

## 4. Verification

- [x] 4.1 Run focused retrieval tests.
- [x] 4.2 Run compile check.
- [x] 4.3 Validate OpenSpec strict.
- [x] 4.4 Re-run a real parsed paper with tables and print final evidence order for a result-oriented question.

## 5. Result Context Quality

- [x] 5.1 Require heuristic result-context chunks to have title/content result signals, not only experiment-like section roles.
- [x] 5.2 Cover generic experiment paragraph exclusion with a retriever regression test.

## 6. Table Context Reranking

- [x] 6.1 Reuse `RerankerPort` to score heuristic table result-context candidates with question + table evidence.
- [x] 6.2 Keep deterministic table graph edges ahead of reranked heuristic context.
- [x] 6.3 Record table context rerank score metadata on expanded chunks.
- [x] 6.4 Cover reranker ordering with a fake reranker regression test.
