## 1. OpenSpec

- [x] 1.1 Add proposal, design, spec, and task artifacts for cross-reference context expander extraction.

## 2. Cross-Reference Expander

- [x] 2.1 Add `retrieval/expanders/cross_ref.py` with `CrossRefContextExpander`.
- [x] 2.2 Update `ResearchRetriever` to delegate `_fetch_refs` behavior to the expander.
- [x] 2.3 Export `CrossRefContextExpander` from the expander package.

## 3. Tests And Validation

- [x] 3.1 Add focused cross-reference expander unit tests.
- [x] 3.2 Run targeted retrieval tests, full RAG tests, compile checks, and `openspec validate extract-cross-ref-context-expander --strict`.
