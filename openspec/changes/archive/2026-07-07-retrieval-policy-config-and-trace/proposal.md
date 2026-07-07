## Why

PRD 16 requires retrieval tuning assets to become observable and version-bound before deeper pipeline refactoring. Current retrieval metadata records the policy name and many values, but not a stable policy config hash or structured trace object.

## What Changes

- Add `RetrievalTrace` and `RetrievalDegradation` models for structured retrieval diagnostics.
- Add stable policy serialization and `retrieval_policy_config_hash` metadata.
- Preserve existing retrieval metadata keys while adding a structured `retrieval_trace` payload.
- Add tests for deterministic policy hash and sparse degradation trace output.

## Capabilities

### New Capabilities

- `paper-rag-retrieval-policy-trace`: Paper RAG retrieval reports stable policy version/hash metadata and structured degradation trace diagnostics.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `business/research/rag/retrieval/trace.py`
  - `business/research/rag/retrieval/policy_config.py`
  - `business/research/rag/retrieval/paper_retriever.py`
  - retrieval tests
- No change to ranking behavior or `RetrievalResult` contract.
