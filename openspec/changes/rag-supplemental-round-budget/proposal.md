## Why

Supplemental answer repair rounds currently consume the same `rounds` and `replans` counters as the main retrieval loop. A valid answer repair can be skipped only because the main loop used the single default replan slot, making production behavior depend on incidental retrieval-loop budget consumption.

## What Changes

- Add a dedicated `generation_policy.max_supplemental_rounds` limit for answer repair retrieval.
- Stop charging supplemental answer repair against main retrieval `rounds` and `replans`; it still consumes deterministic query, source-read, memory-hit, context, and worker-call budgets.
- Emit structured skip reason codes when supplemental repair is skipped.
- Add metrics for supplemental skip reasons.
- Update generation phase tests for independent supplemental budget and explicit budget exhaustion.

## Capabilities

### New Capabilities
- `rag-supplemental-round-budget`: bounded supplemental answer repair budget and diagnosable skip reasons.

### Modified Capabilities

## Impact

- Affected code: `framework/harness/rag/session.py`, `framework/harness/rag/policy.py`, `framework/harness/rag/metrics.py`, and generation phase tests.
- No external API schema, storage, retrieval adapter, or LLM worker contract changes are expected.
