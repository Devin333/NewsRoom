## 1. OpenSpec

- [x] 1.1 Add proposal, design, spec, and task artifacts for formula context expander extraction.

## 2. Formula Context Expander

- [x] 2.1 Add `retrieval/expanders/formula_context.py` with `FormulaContextExpander`.
- [x] 2.2 Update `ResearchRetriever._structural_context_refs` to delegate formula branches to the expander.
- [x] 2.3 Export `FormulaContextExpander` from the expander package.

## 3. Tests And Validation

- [x] 3.1 Add focused formula context expander unit tests.
- [x] 3.2 Run targeted retrieval tests, full RAG tests, compile checks, and `openspec validate extract-formula-context-expander --strict`.
