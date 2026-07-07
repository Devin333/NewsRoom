## Why

The gated RAG answer phase currently abstains after a single deterministic answer-gate failure, even when the gate exposes unsupported claims that could drive a bounded follow-up retrieval round. This leaves the Agentic RAG loop safer than the legacy path, but overly conservative and unable to use answer verification feedback to improve evidence coverage.

## What Changes

- Consume `generation_policy.max_attempts` in `BoundedRAGSessionController`.
- Feed unsupported claims from failed answer gates back into `state.gap_report`.
- Run at most one controlled supplemental retrieval round per failed generation attempt while reusing the existing planner, plan gates, source verifier, context assembler, and replan budget.
- Reassemble the context pack and retry answer generation when supplemental evidence is accepted.
- Preserve safe abstention when the answer gate still fails, unsupported claims are absent, or replan/round budget is exhausted.
- Configure production paper RAG answer sessions with two generation attempts.

## Capabilities

### New Capabilities
- `rag-answer-supplemental-round`: Harness RAG can use unsupported answer claims to perform bounded supplemental retrieval before final abstention.

### Modified Capabilities

## Impact

- Affected framework modules: `framework/harness/rag/session.py`.
- Affected interface modules: `interfaces/services/paper_rag_factory.py`.
- Affected tests: framework RAG generation phase regressions.
