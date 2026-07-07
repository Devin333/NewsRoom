## Context

`ResearchRetriever` is still the public paper retrieval entrypoint, and downstream code imports `ResearchRetriever`, `RetrievalRequest`, and `RetrievalResult` from `paper_retriever.py`. Recent PRD 16 slices already extracted planning, recall, rerank scoring, child scoring, and context expanders into separate modules, so `retrieve()` is now mostly orchestration plus metrics assembly.

## Goals / Non-Goals

**Goals:**

- Introduce a `RetrievalPipeline` object that owns the end-to-end retrieval orchestration.
- Keep `ResearchRetriever.retrieve()` as a thin delegate to the pipeline.
- Preserve `RetrievalResult`, metadata keys, policy behavior, and existing test expectations.
- Keep this slice compatible with future policy YAML and parser cascade work.

**Non-Goals:**

- Do not move `RetrievalPolicy`, `RetrievalRequest`, or `RetrievalResult` in this slice.
- Do not change scoring, reranking, fusion, context expansion, or metric semantics.
- Do not add policy YAML loading or parser cascade behavior.

## Decisions

- **Pipeline receives stage objects instead of constructing stores:** `ResearchRetriever` already wires all ports and stage dependencies. Passing initialized dependencies into `RetrievalPipeline` keeps this refactor behavior-preserving and avoids broad factory churn.
- **Keep helper functions colocated with pipeline orchestration:** metrics helpers such as `_field_hits_by_name`, `_metadata_extreme`, and `_dedupe_chunks` move with the orchestration code because they serve result assembly rather than the public retriever entrypoint.
- **Preserve public imports through `paper_retriever.py`:** downstream imports remain valid. The retrieval package also exports `RetrievalPipeline` for direct tests and future factory wiring.
- **No stage registry yet:** PRD 16 ultimately wants declarative stage activation, but this slice only introduces the pipeline boundary. Registry work can happen after the entrypoint has a stable object to delegate to.

## Risks / Trade-offs

- **Temporary constructor verbosity** -> The pipeline constructor will receive several stage objects. This is acceptable for the transition and can later be replaced by a factory or registry.
- **`paper_retriever.py` remains larger than final target** -> Policy DTOs and construction still live there. This slice reduces orchestration coupling first; policy config migration can shrink the file further.
- **Metric drift risk** -> Existing `test_retriever.py` plus a focused pipeline delegation test verify that result shape and metadata remain stable.
