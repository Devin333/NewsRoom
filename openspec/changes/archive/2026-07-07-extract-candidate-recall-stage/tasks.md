## 1. OpenSpec

- [x] 1.1 Add proposal, design, spec, and task artifacts for candidate recall stage extraction.

## 2. Candidate Recall Stage

- [x] 2.1 Add `retrieval/recall_stage.py` with `CandidateRecallStage` and `CandidateRecallResult`.
- [x] 2.2 Update `ResearchRetriever` to delegate candidate recall and hybrid fusion to the stage.
- [x] 2.3 Export `CandidateRecallStage` from the retrieval package.

## 3. Tests And Validation

- [x] 3.1 Add focused candidate recall stage unit tests.
- [x] 3.2 Run targeted retrieval tests, full RAG tests, compile checks, and `openspec validate extract-candidate-recall-stage --strict`.
