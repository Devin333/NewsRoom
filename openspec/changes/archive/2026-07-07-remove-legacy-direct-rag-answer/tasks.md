## 1. Service Removal

- [x] 1.1 Remove direct answer generation from `PaperRagApplicationService`.
- [x] 1.2 Make `generate=True, gated=False` fail closed before retrieval.
- [x] 1.3 Preserve retrieve-only behavior.

## 2. CLI Removal

- [x] 2.1 Remove `paper ask --legacy-direct-answer`.
- [x] 2.2 Ensure `paper ask --answer` still routes through gated Harness.

## 3. Tests And Validation

- [x] 3.1 Update service tests for fail-closed legacy direct calls.
- [x] 3.2 Update CLI registration tests for removed legacy flag.
- [x] 3.3 Run targeted tests, compile, smoke, and strict OpenSpec validation.
