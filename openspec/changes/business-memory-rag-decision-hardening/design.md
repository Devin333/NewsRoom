## Context

The framework scoring runtime is intentionally independent of memory. Memory/RAG decision logic belongs in business code and should produce plain `FeatureVector` objects that can be merged into scoring inputs.

## Design

- `BusinessMemoryHit` normalizes results from vector search, framework memory search, or dict-like result sets.
- `BusinessMemoryContext` aggregates hits and exposes a stable feature dictionary.
- `BusinessMemoryRecallService` accepts an optional `BusinessMemorySearchPort`; if absent or failing, it returns an empty context.
- Decision helpers estimate source reliability, duplicate risk, topic momentum, previous misrank penalty, and historical noise penalty using deterministic metadata rules.
- `BusinessMemoryDecisionService` builds memory feature vectors for cards and exposes context for diagnostics.
- `BoardScoringService` accepts an optional memory decision service and merges memory features before runtime scoring.

## Constraints

- No direct Qdrant dependency in business memory.
- No framework scoring dependency on business memory.
- No existing board workflow migration in this change.
