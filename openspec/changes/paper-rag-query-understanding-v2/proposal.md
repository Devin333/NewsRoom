# Paper RAG Query Understanding V2

## Why

`blind_semantic` makes benchmark questions more realistic, but natural questions still need reliable query understanding and route observability. The current retriever exposes a primary intent, while the benchmark report does not summarize which evidence routes were used.

## What Changes

- Expand natural-language query intent rules for quantitative evidence, visual evidence, mathematical relations, and result takeaways.
- Add a route plan to `RetrievalRoute` so a single question can declare multiple evidence recall routes.
- Record route plan metadata in retrieval results and evidence evaluation samples.
- Add route and intent distribution to JSON/Markdown benchmark reports.
- Keep default policy behavior compatible; V3 field embedding and V5 reranker are out of scope.

## Out Of Scope

- Training a model or adding a new external reranker.
- Enabling production policy promotion gates.
- Wiring full field-level embedding into benchmark.
