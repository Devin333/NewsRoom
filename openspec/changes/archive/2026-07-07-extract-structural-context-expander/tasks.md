## 1. OpenSpec

- [x] 1.1 Add proposal, design, spec, and task artifacts for structural context expander extraction.

## 2. Structural Context Expander

- [x] 2.1 Add `retrieval/expanders/structural.py` with `StructuralContextExpander`.
- [x] 2.2 Update `ResearchRetriever` to delegate `_interleave_structural_context` behavior to the expander.
- [x] 2.3 Export `StructuralContextExpander` from the expander package.

## 3. Tests And Validation

- [x] 3.1 Add focused structural context expander unit tests.
- [x] 3.2 Run targeted retrieval tests, full RAG tests, compile checks, and `openspec validate extract-structural-context-expander --strict`.
