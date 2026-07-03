## 1. OpenSpec

- [x] 1.1 Add proposal, design, spec, and task artifacts for child candidate scorer extraction.

## 2. Child Candidate Scorer

- [x] 2.1 Add `retrieval/scoring.py` with `ChildCandidateScorer` and scoring helper functions.
- [x] 2.2 Update `RetrievalPolicy` to use scoring module normalization helpers.
- [x] 2.3 Update `ResearchRetriever` to delegate child scoring to `ChildCandidateScorer`.
- [x] 2.4 Export `ChildCandidateScorer` from the retrieval package.

## 3. Tests And Validation

- [x] 3.1 Add focused child candidate scorer unit tests.
- [x] 3.2 Run targeted retrieval tests, full RAG tests, compile checks, and `openspec validate extract-child-candidate-scorer --strict`.
