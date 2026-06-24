## 1. Retrieval Design

- [ ] 1.1 Audit current `ResearchRetriever` evidence assembly and query intent routing for table/result questions.
- [ ] 1.2 Define a bounded table context expansion policy with per-table and global budgets.
- [ ] 1.3 Decide which intents trigger expansion: `table_query`, `numerical_result`, `comparison`, and result-style questions.

## 2. Implementation

- [ ] 2.1 Add a retrieval helper that expands table chunks through `nearby_context_chunk_id`, `referenced_by_chunks`, `parent_chunk_id`, and `parent_table_chunk_id`.
- [ ] 2.2 Add role/title-prioritized result context selection for experiment, analysis, result, ablation, evaluation, and conclusion sections.
- [ ] 2.3 Deduplicate expanded chunks and annotate expansion metadata.
- [ ] 2.4 Preserve existing text/image fusion scoring and do not change parser output.

## 3. Tests

- [ ] 3.1 Unit test: table chunk hit expands to nearby context and explicit referencing paragraph.
- [ ] 3.2 Unit test: row-group table hit expands to parent table chunk.
- [ ] 3.3 Unit test: result/conclusion paragraph is included only within budget and same paper.
- [ ] 3.4 Unit test: missing referenced chunk is skipped without failure.

## 4. Verification

- [ ] 4.1 Run focused retrieval tests.
- [ ] 4.2 Run compile check.
- [ ] 4.3 Validate OpenSpec strict.
- [ ] 4.4 Re-run a real parsed paper with tables and print final evidence order for a result-oriented question.
