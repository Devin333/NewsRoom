## 1. Specification

- [x] 1.1 Validate the OpenSpec change artifacts.

## 2. Live Answer Eval Runner

- [x] 2.1 Add a business-owned live answer eval runner that reuses fixture paper generation.
- [x] 2.2 Add a `scripts.dev run-live-answer-eval` command.

## 3. Workflow

- [x] 3.1 Add a scheduled/manual GitHub Actions workflow for live answer eval.
- [x] 3.2 Upload live answer eval artifacts and guard missing LLM secrets.

## 4. Tests

- [x] 4.1 Add unit coverage for the live answer eval runner with an injected fake ask callable.
- [x] 4.2 Add contract coverage for the dev command and workflow.
- [x] 4.3 Run targeted tests and OpenSpec validation.
