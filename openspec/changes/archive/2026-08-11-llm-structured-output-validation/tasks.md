## 1. OpenSpec Setup

- [x] 1.1 Create `llm-structured-output-validation` OpenSpec change.
- [x] 1.2 Define proposal, design, tasks, and spec delta.
- [x] 1.3 Keep OpenSpec files, local state, generated outputs, and secrets out of commits.

## 2. Structured Output Validation

- [x] 2.1 Add JSON Schema subset validator.
- [x] 2.2 Wire validator into OpenAI-compatible structured output parsing.
- [x] 2.3 Return non-retryable structured validation provider errors.
- [x] 2.4 Export validator primitives from LLM package.

## 3. Validation

- [x] 3.1 Add focused structured output validation tests.
- [x] 3.2 Run OpenSpec validation and focused tests.
- [x] 3.3 Run full tests, diff checks, secret scan, and commit.
