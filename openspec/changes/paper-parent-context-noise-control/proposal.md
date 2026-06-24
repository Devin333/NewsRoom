## Why

Research retrieval currently expands matched child chunks to their parent chunks so answers can see the surrounding section context. This improves completeness, but it can also introduce noise: one precise paragraph hit may pull an entire long section into evidence, increasing prompt size and giving the model unrelated material.

## What Changes

- Add independent parent expansion budgets for parent count and approximate token volume.
- Trim oversized parent chunks into child-anchored snippets instead of returning the full section by default.
- Reuse the existing `RerankerPort` to filter and order parent candidates when a reranker is configured.
- Vary parent expansion budgets by query intent so method/concept questions can keep more section context while table/fact/result questions stay tighter.
- Annotate parent expansion metadata so downstream evidence inspection can explain why a parent or snippet was included.

## Capabilities

### New Capabilities
- `paper-parent-context-noise-control`: Defines bounded, traceable parent context expansion for research paper RAG.

### Modified Capabilities
- `research-runtime`: Research retrieval must keep parent context helpful while preventing long or weakly related parents from flooding the evidence set.

## Impact

- Likely affects `business/research/rag/retriever.py`, `business/research/rag/retrieval_port.py`, and focused retriever tests.
- No parser, chunk payload, vector schema, or database migration is required.
- Existing parent-child chunk relationships remain the input signal; the change is retrieval-time assembly only.
