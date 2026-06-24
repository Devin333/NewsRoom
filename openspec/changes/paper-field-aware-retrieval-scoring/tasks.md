## 1. Retrieval Design

- [x] 1.1 Add policy fields for field weights and child score blend weights.
- [x] 1.2 Define deterministic field score extraction for title, abstract, caption, equation, and body.
- [x] 1.3 Define field scoring metadata and retrieval-level metrics.

## 2. Implementation

- [x] 2.1 Compute field score breakdown for child candidates.
- [x] 2.2 Blend semantic score, field score, and position score into `child_final_score`.
- [x] 2.3 Use `child_final_score` for child candidate ordering.
- [x] 2.4 Preserve visual fusion, table expansion, and parent expansion behavior.
- [x] 2.5 Expose field score metadata through evidence candidates and evidence packs.
- [x] 2.6 Add retrieval-level field scoring metrics.

## 3. Tests

- [x] 3.1 Unit test: figure query boosts caption-matching figure chunks.
- [x] 3.2 Unit test: formula query boosts formula latex/description matching chunks.
- [x] 3.3 Unit test: contribution query boosts abstract/title matching chunks.
- [x] 3.4 Unit test: method query boosts section-title matching chunks.
- [x] 3.5 Unit test: field score metadata is exposed through evidence packs.
- [x] 3.6 Regression test: parent and table expansion still run with field-aware child scoring.

## 4. Verification

- [x] 4.1 Run focused research RAG tests.
- [x] 4.2 Run compile check.
- [x] 4.3 Validate OpenSpec strict.
