## Why

The current RAG answer gate verifies cited evidence ids, but it does not verify that each answer claim is grounded to a concrete source span from the verified context pack. The enterprise RAG review identifies span-level citation verification as the next trust gap after evidence-id citation integrity.

## What Changes

- Add span references to grounded answer claims so a candidate answer can bind each claim to concrete context-pack spans.
- Extend the deterministic RAG answer gate to reject claims whose cited spans are missing, unknown, or attached to evidence outside the claim's cited evidence ids.
- Preserve abstention compatibility: abstained candidates do not need claim span references.
- Expose verified citation span references through the Paper RAG service response.

## Capabilities

### New Capabilities
- `rag-answer-span-citation-gate`: deterministic span-level citation verification for Harness RAG answer candidates.

### Modified Capabilities

## Impact

Affected code includes `framework/harness/rag` answer models and gates, Paper RAG answer service serialization, and focused RAG tests. No database migration, external service dependency, or LLM routing change is required.
