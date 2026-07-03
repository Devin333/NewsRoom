## 1. OpenSpec

- [x] 1.1 Add proposal, design, spec, and task artifacts for child ranking stage extraction.

## 2. Child Ranking Stage

- [x] 2.1 Add `retrieval/ranking_stage.py` with `ChildRankingStage` and `ChildRankingResult`.
- [x] 2.2 Move rerank thresholding, field rerank scoring, child scoring, visual fusion, sorting, and top child selection from `pipeline.py` into the stage.
- [x] 2.3 Update `RetrievalPipeline` to delegate child ranking and consume the structured result.
- [x] 2.4 Export `ChildRankingStage` from the retrieval package.

## 3. Tests And Validation

- [x] 3.1 Add focused child ranking stage tests.
- [x] 3.2 Run targeted retrieval tests, full RAG tests, compile checks, and `openspec validate extract-child-ranking-stage --strict`.
