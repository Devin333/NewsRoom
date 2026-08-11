# Change: Gate provider structured output releases with reproducible evaluation

## Why

The managed structured-output path can negotiate and validate provider projections, but a deployment capability revision can still be configured from a provider claim or one successful example. Native strict and constrained decoding need versioned, repeatable evidence across schema coverage and held-out Research quality before they can alter production enforcement.

## What Changes

- Add a versioned, provenance-bearing schema and held-out Research evaluation corpus.
- Add deterministic multi-metric evaluation that independently gates schema correctness, first-pass and repair validity, answer quality, evidence grounding, citation completeness, provider rejection, latency, tokens, and cost.
- Add immutable provider release records with Harness-owned approval, rollout state, workflow scope, evidence identity, and rollback target.
- Require native strict and constrained projections to reference an approved enabled release; shadow records remain observable but cannot change the provider payload.
- Keep the current DashScope deployment held and disabled until real provider evidence exists.

## Impact

- Affected spec: `llm-structured-output`
- Affected code: `framework/llm/structured_output`, `framework/llm/clients/config.py`, `framework/llm/routing`, `configs/llm/structured_output`, evaluation CLI, and focused tests.
- Existing local validation remains mandatory in every rollout state and is never a rollback target.
