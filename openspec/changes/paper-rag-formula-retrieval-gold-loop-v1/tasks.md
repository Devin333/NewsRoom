## 1. Formula Normalization

- [x] 1.1 Add formula normalization helper for normalized LaTeX, symbols, operators, structure tokens, labels, and context terms.
- [x] 1.2 Route formula field extraction through normalized metadata while preserving existing formula fields.
- [x] 1.3 Add unit tests for common LaTeX forms, equation labels, operators, symbols, and field text extraction.

## 2. Formula Retrieval Policy And Sparse Scoring

- [x] 2.1 Add named `paper_formula_rag_v1` policy without changing default or existing benchmark policies.
- [x] 2.2 Add formula-specific sparse score components for symbols, operators, labels, structure, and context.
- [x] 2.3 Blend formula sparse score into formula policy ranking and preserve score metadata in returned chunks.
- [x] 2.4 Add retriever tests proving formula sparse and label matches can lift formula evidence into top ranks.

## 3. Formula Explanation Graph Expansion

- [x] 3.1 Strengthen formula explanation expansion to use referenced text, referenced-by links, parent context, and explicit equation references.
- [x] 3.2 Preserve expansion metadata, graph score, and source locator inheritance for formula context chunks.
- [x] 3.3 Add tests for formula-to-explanation and explanation-to-formula expansion.

## 4. Formula Diagnostics And Gold Quality Loop

- [x] 4.1 Add formula failure reason classification and score breakdown output for missed formula gold evidence.
- [x] 4.2 Extend benchmark/gold quality reporting so formula blind semantic warnings are judgeable and repairable.
- [x] 4.3 Add tests for formula diagnostics, gold judge reasons, and report fields.

## 5. Validation

- [x] 5.1 Run targeted Paper RAG retrieval/evaluation tests.
- [x] 5.2 Run `openspec validate paper-rag-formula-retrieval-gold-loop-v1 --strict`.
- [x] 5.3 Run compile checks.
- [x] 5.4 Run a real benchmark comparison when local paper data is available.
- [x] 5.5 Commit completed implementation changes.
