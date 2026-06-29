# Paper RAG Evidence Pack Grounding V1

## Why

The blind semantic policy generalizes at retrieval level on the held-out 50-paper set, but answer-level promotion still fails because `missing_gold_in_retrieval` mixes true missing evidence with cases where an equivalent paragraph, formula, or neighboring context supports the answer without matching the exact `gold_chunk_id`.

Paper RAG needs an explicit evidence-group layer so benchmark gold, retrieval reports, and answer evaluation can distinguish strict gold-id hits from equivalent grounded evidence.

## What Changes

- Add evidence-group metadata to generated Paper RAG QA pairs.
- Add equivalent gold ids derived from source locators, parent/nearby relationships, and references.
- Report strict and equivalent retrieval coverage side by side.
- Pass equivalent gold ids into answer evaluation so supported equivalent evidence is not mislabeled as strict missing gold.
- Preserve strict gold metrics so promotion cannot hide regressions.

## Out Of Scope

- Training a new reranker or embedding model.
- Making the evidence-pack policy the production default.
- Implementing the full claim-level neural/LLM judge path.
- Treating arbitrary semantically similar chunks as equivalent evidence.
