## 1. OpenSpec

- [x] 1.1 Add proposal, design, spec, and task artifacts for supplemental table hit expander extraction.

## 2. Supplemental Table Hit Expander

- [x] 2.1 Add `retrieval/expanders/supplemental_table.py` with `SupplementalTableHitExpander`.
- [x] 2.2 Update `ResearchRetriever` to delegate `_supplemental_table_hits` behavior to the expander.
- [x] 2.3 Export `SupplementalTableHitExpander` from the expander and retrieval packages.

## 3. Tests And Validation

- [x] 3.1 Add focused supplemental table hit expander unit tests.
- [x] 3.2 Run targeted retrieval tests, full RAG tests, compile checks, and `openspec validate extract-supplemental-table-hit-expander --strict`.
