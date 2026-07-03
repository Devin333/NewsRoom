## 1. OpenSpec

- [x] 1.1 Add proposal, design, spec, and task artifacts for table context expander extraction.

## 2. Table Context Expander

- [x] 2.1 Add `retrieval/expanders/table_context.py` with `TableContextExpander`.
- [x] 2.2 Update `ResearchRetriever` to delegate `_fetch_table_context` behavior to the expander.
- [x] 2.3 Export `TableContextExpander` from the expander package.

## 3. Tests And Validation

- [x] 3.1 Add focused table context expander unit tests.
- [x] 3.2 Run targeted retrieval tests, full RAG tests, compile checks, and `openspec validate extract-table-context-expander --strict`.
