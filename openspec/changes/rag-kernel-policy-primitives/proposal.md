## Why

The PRD calls for `framework/rag/core/policy.py`. Research currently owns a few generic retrieval-policy calculations inline: intent allow-list checks, section-distance position decay, and intent-specific context budgets. The concrete Paper policy fields and weights should remain in Research, but these pure calculations are domain-neutral.

## What Changes

- Add `framework/rag/core/policy.py`.
- Introduce `intent_allowed()`, `position_decay_score()`, and `intent_budget()`.
- Rewire `RetrievalPolicy` methods to call the kernel helpers while preserving Paper policy configuration and metadata.
- Keep Paper-specific intent names, field weights, visual fusion weights, parent scoring weights, and named policy construction in Research.
- Add framework unit tests for policy primitives.

## Capabilities

### New Capabilities

- `rag-kernel-policy-primitives`: domain-neutral retrieval policy helper functions.

### Modified Capabilities

- `paper-rag-policy-primitive-migration`: Paper retrieval policy delegates generic calculations to the RAG kernel while preserving Paper-specific policy values.

## Impact

Affected code is limited to `framework/rag/core`, `ResearchRetriever` policy methods, tests, and this OpenSpec change. Existing Paper policy outputs remain compatible.
