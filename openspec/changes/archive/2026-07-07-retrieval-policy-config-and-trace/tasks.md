## 1. Policy Hash

- [x] 1.1 Add OpenSpec proposal, design, spec, and task artifacts.
- [x] 1.2 Add `policy_config.py` helpers for stable policy dict and hash.
- [x] 1.3 Include policy hash/version fields in retrieval metadata.

## 2. Structured Trace

- [x] 2.1 Add `RetrievalDegradation` and `RetrievalTrace` models.
- [x] 2.2 Replace ad hoc degradation append helper with typed degradation serialization.
- [x] 2.3 Include `retrieval_trace` in retrieval metadata while preserving compatibility keys.

## 3. Tests And Validation

- [x] 3.1 Add tests for deterministic policy hash.
- [x] 3.2 Update sparse degradation test to assert structured trace metadata.
- [x] 3.3 Run retrieval tests, compile checks, and `openspec validate retrieval-policy-config-and-trace --strict`.
