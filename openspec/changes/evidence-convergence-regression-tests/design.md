## Context

P0-A and P0-B closed production relevance scoring and answer supplemental retrieval. The next review gap is not a new runtime feature; it is missing proof that two existing safety boundaries keep working across the real business RAG route.

The important path is: Paper chunk -> Research adapter -> kernel evidence -> Harness evidence candidate -> source gates -> session status. A framework-only fake would not prove content-derived Research evidence typing.

## Goals / Non-Goals

**Goals:**
- Add a business integration test that proves method evidence cannot satisfy an experiment requirement.
- Add golden compatibility coverage for old rows that lack `expected_behavior`.
- Add a gated service regression for expected abstention behavior.

**Non-Goals:**
- Rewrite or regenerate the full 67-row legacy golden dataset.
- Add CI workflows for eval jobs.
- Change retrieval ranking, answer generation prompts, or production policy thresholds.

## Decisions

1. Keep the convergence test on the real adapter boundary.

   The test uses `PaperChunkRetrievalPort` and `BoundedRAGSessionController`, with a fake paper retriever that returns only a method chunk. This proves the business evidence resolver, not just the framework gate.

2. Keep legacy golden files backward compatible.

   The loader already defaults missing `expected_behavior` to `answer`. A regression against `data/eval/golden_set.json` is enough to protect compatibility without noisy data churn.

3. Test gated abstention with a small golden row.

   A negative `EvidenceQAPair` drives service assertions for `status="abstained"`, `answer is None`, and empty citations. This proves the expected-abstain contract at the service boundary without invoking external LLMs.

## Risks / Trade-offs

- The gated abstention regression uses a fake session result -> it verifies service contract and golden behavior, not live model quality.
- The convergence regression uses a fake retriever -> it still crosses the production adapter and Harness gates, but does not prove Qdrant recall quality.
