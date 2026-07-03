## 1. Config Loading

- [x] 1.1 Add retrieval policy config env constant and loader.
- [x] 1.2 Apply config `base_policy` plus validated overrides to `RetrievalPolicy`.
- [x] 1.3 Preserve existing named policy behavior without config.

## 2. Tests

- [x] 2.1 Add tests for YAML/JSON config loading and effective overrides.
- [x] 2.2 Add tests for validation failures and env fallback behavior.
- [x] 2.3 Add tests proving configured policy hashes change.

## 3. Validation

- [x] 3.1 Run targeted retrieval policy tests.
- [x] 3.2 Run compile, smoke/full checks, and strict OpenSpec validation.
