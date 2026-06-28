# Paper RAG Field Embedding V3

## Why

The retriever already has a `FieldEmbeddingSearchPort`, but the real benchmark live path does not build or inject a field index. As a result, field embedding score components stay at zero in blind benchmark reports, and fields such as captions, equations, table rows, and visual descriptions do not act as independent semantic recall channels.

## What Changes

- Expand paper field text extraction with explicit `table_rows`, `table_columns`, `visual_description`, and `referenced_text` fields.
- Add an in-memory field embedding index to the real benchmark/live evaluation path.
- Keep deterministic lexical field scoring compatible with the existing core fields.
- Surface field embedding distribution in JSON and Markdown reports.
- Add tests proving field embeddings are non-zero in live evaluation and benchmark reports.

## Out Of Scope

- Downloading or training a new embedding model.
- Replacing the production Qdrant-backed `PaperFieldChunkStore`.
- Promoting a new production retrieval policy.
