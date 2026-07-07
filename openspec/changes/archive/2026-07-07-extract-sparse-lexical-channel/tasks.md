## 1. Sparse Channel Extraction

- [x] 1.1 Add OpenSpec proposal, design, spec, and task artifacts.
- [x] 1.2 Add `SparseLexicalChannel` under `retrieval/channels/` with BM25 index load, fallback, and formula sparse fallback.
- [x] 1.3 Delegate `ResearchRetriever._sparse_lexical_candidates` to the channel.
- [x] 1.4 Export sparse formula scoring helpers needed by retriever child scoring.

## 2. Tests And Validation

- [x] 2.1 Add sparse channel tests for persisted BM25, missing fallback, and formula fallback.
- [x] 2.2 Run retrieval tests, compile checks, and `openspec validate extract-sparse-lexical-channel --strict`.
