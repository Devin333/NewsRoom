## Why

Research retrieval already combines semantic relevance, position, visual fusion, table context expansion, and explicit parent scoring. However, child chunk ranking still treats each chunk mostly as one text blob. Academic paper chunks carry richer field structure: section titles, abstract chunks, figure/table captions, and formula text/descriptions.

When a user asks a figure, formula, contribution, or method question, the strongest signal may live in a specific field rather than in the whole chunk body. Retrieval should be able to explain whether a hit was boosted by title, abstract, caption, equation, or body relevance.

## What Changes

- Add field-aware scoring for child retrieval candidates.
- Compute `title_score`, `abstract_score`, `caption_score`, `equation_score`, `body_score`, and weighted `field_score`.
- Blend semantic score, field score, and normalized position score into `child_final_score`.
- Use intent-specific field weights so figure/table/formula/contribution/method questions emphasize the right fields.
- Expose field score breakdown metadata through evidence candidates and evidence packs.
- Add retrieval-level field scoring observability metrics.

## Capabilities

### New Capabilities
- `paper-field-aware-retrieval-scoring`: Defines field-aware retrieval scoring for research paper RAG.

### Modified Capabilities
- `research-runtime`: Research retrieval must expose field-level relevance signals when ranking paper chunks.

## Impact

- Affects `business/research/rag/retriever.py`, `business/research/rag/retrieval_port.py`, and focused RAG tests.
- No parser, OCR, vector store, database, or persistent chunk schema migration is required.
- Existing table expansion, parent expansion, and visual fusion remain in place.
