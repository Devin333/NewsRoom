# Paper RAG Lightweight Reranker V5

## Why

Blind semantic benchmark runs now expose field embedding and structural context, but ranking is still weak for formula/table/result questions. The retriever already supports a `RerankerPort`, yet the benchmark live path does not provide a lightweight reranker that can be enabled without downloading a model or changing the default policy.

## What Changes

- Add a deterministic lightweight lexical reranker implementing `RerankerPort`.
- Make live evidence/benchmark retrieval accept an explicit lightweight reranker switch.
- Use structured field passages for reranking, including section, chunk type, captions, equations, table rows, visual descriptions, referenced text, and body.
- Surface rerank distribution in evidence and benchmark reports.
- Keep the default retrieval behavior unchanged unless the switch is enabled.

## Out Of Scope

- Training or downloading a neural reranker.
- Promoting a new default retrieval policy.
- Replacing field embedding or visual retrieval.
