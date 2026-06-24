## 1. Formula Reference Detection

- [x] 1.1 Add deterministic regex helpers for `Eq. (1)`, `Equation 1`, and `閸忣剙绱?1)` references.
- [x] 1.2 Build formula lookup keys from equation id, number, label, and normalized aliases.

## 2. Chunk Metadata

- [x] 2.1 Add `formula_references` metadata to paragraph chunks for matched known equations.
- [x] 2.2 Add `referenced_by_chunks` and `reference_labels` metadata to formula chunks.
- [x] 2.3 Preserve existing `parent_chunk_id`, `source_locator`, and `formula_parent_match_strategy` behavior.

## 3. Tests

- [x] 3.1 Cover one formula referenced by multiple later paragraphs.
- [x] 3.2 Cover unknown equation references not creating edges.
- [x] 3.3 Cover source locator preservation when references appear on different pages.

## 4. Verification

- [x] 4.1 Run focused chunker tests.
- [x] 4.2 Run compile check.
- [x] 4.3 Validate OpenSpec strict.
- [x] 4.4 Re-chunk a real paper artifact and inspect formula metadata.
