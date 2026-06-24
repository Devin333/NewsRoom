## 1. Retrieval Design

- [x] 1.1 Add policy fields for default and intent-specific parent score weights.
- [x] 1.2 Define section heading score rules for method, contribution, result, comparison, table, and formula intents.
- [x] 1.3 Define parent score metadata for evidence inspection.

## 2. Implementation

- [x] 2.1 Compute child relevance, parent relevance, heading score, position score, and final score for parent candidates.
- [x] 2.2 Use `parent_final_score` as parent ordering with child rank tie-break.
- [x] 2.3 Preserve deterministic scoring when reranker is missing, fails, or returns malformed scores.
- [x] 2.4 Apply intent-specific score weights.
- [x] 2.5 Expose parent score breakdown through evidence candidates and evidence packs.
- [x] 2.6 Add retrieval-level parent scoring metrics.

## 3. Tests

- [x] 3.1 Unit test: parent final score can override raw child rank when heading/relevance is stronger.
- [x] 3.2 Unit test: parent reranker score contributes to parent final score and metadata.
- [x] 3.3 Unit test: numerical-result query prefers result/experiment/conclusion heading over unrelated heading.
- [x] 3.4 Unit test: concept-method query prefers method/architecture heading.
- [x] 3.5 Unit test: reranker failure still produces deterministic score metadata.
- [x] 3.6 Unit test: evidence pack exposes score breakdown metadata.

## 4. Verification

- [x] 4.1 Run focused research RAG tests.
- [x] 4.2 Run compile check.
- [x] 4.3 Validate OpenSpec strict.
