## 1. OpenSpec

- [x] 1.1 Add proposal, design, spec, and task artifacts for parent context expander extraction.

## 2. Parent Expander

- [x] 2.1 Add `retrieval/expanders/base.py` with a minimal context expander protocol.
- [x] 2.2 Add `retrieval/expanders/parent.py` with `ParentContextExpander`.
- [x] 2.3 Update `ResearchRetriever` to delegate parent expansion to `ParentContextExpander`.
- [x] 2.4 Export the expander package types.

## 3. Tests And Validation

- [x] 3.1 Add focused parent expander unit tests.
- [x] 3.2 Run targeted retrieval tests, full RAG tests, compile checks, and `openspec validate extract-parent-context-expander --strict`.
