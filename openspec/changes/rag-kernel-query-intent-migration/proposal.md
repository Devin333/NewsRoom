## Why

The PRD calls for `framework/rag/retrieval/query_intent.py`. Research currently owns a small rule-based query intent classifier inline in `routing.py`. The Paper-specific intent names, signals, filters, and route construction should stay in Research, but the rule matching mechanism is domain-neutral and reusable by future RAG adapters.

## What Changes

- Add `framework/rag/retrieval/query_intent.py`.
- Introduce `QueryIntentRule`, `build_query_intent_rules()`, and `classify_query_intent_by_rules()`.
- Rewire Research query intent classification to use the kernel rule matcher while preserving Paper-specific rule order and route behavior.
- Keep Paper-specific route construction, filters, section roles, and intent names in Research.
- Add framework unit tests for rule ordering, fallback behavior, and validation.

## Capabilities

### New Capabilities

- `rag-kernel-query-intent`: domain-neutral rule-based query intent matching.

### Modified Capabilities

- `paper-rag-query-intent-migration`: Paper routing delegates generic rule matching to the RAG kernel while preserving Paper route semantics.

## Impact

Affected code is limited to `framework/rag/retrieval`, `business/research/rag/routing.py`, targeted tests, and this OpenSpec change. Existing Research route outputs remain compatible.
