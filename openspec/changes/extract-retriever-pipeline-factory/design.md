## Context

`ResearchRetriever.__init__` is now the last large block inside `paper_retriever.py`. It creates dense/sparse/field/claim/visual channels, recall/ranking stages, rerank cascade, expanders, and the pipeline. That wiring is useful, but it is not part of the retriever's public entrypoint contract.

## Goals / Non-Goals

**Goals:**

- Move retrieval pipeline composition into a dedicated factory module.
- Keep `ResearchRetriever` constructor arguments and behavior unchanged.
- Reduce `paper_retriever.py` below the PRD 16 thin-entrypoint line target.

**Non-Goals:**

- Do not introduce dependency injection containers.
- Do not change stage construction order.
- Do not change channel availability metadata.
- Do not alter policy values or retrieval scoring.

## Decisions

- **Factory returns a configured `RetrievalPipeline`:** The retriever only stores the chunk store, selected policy, and pipeline.
- **Factory accepts the same optional adapters:** Reranker, field index, field reranker, visual store, and claim index stay explicit parameters.
- **No channel attributes on `ResearchRetriever`:** Tests and production code do not rely on private channel attributes, so they can live only inside the factory.

## Risks / Trade-offs

- **Factory has many imports:** This is acceptable because it is the composition root for retrieval internals.
- **Thin retriever delegates more completely:** Debugging still has clear boundaries because each stage remains a named module.
