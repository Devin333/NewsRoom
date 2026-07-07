## 1. Public Payload Sanitization

- [x] 1.1 Add recursive Paper RAG public metrics sanitization for user and namespace scope fields.
- [x] 1.2 Apply sanitization to retrieve-only response metrics.
- [x] 1.3 Apply sanitization to gated response metrics while preserving tenant id and operational counters.

## 2. Tests And Validation

- [x] 2.1 Update retrieve-only and gated service tests to prove public payload filtering and internal scope preservation.
- [x] 2.2 Run targeted tests, OpenSpec strict validation, compile, smoke, all OpenSpec strict validation, and diff checks.
