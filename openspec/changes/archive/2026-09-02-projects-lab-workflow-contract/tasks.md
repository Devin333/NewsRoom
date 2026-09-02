# Tasks

## 1. Contract fixtures and domain rules

- [x] 1.1 Add canonical stage, next_action, and error-code fixtures. Depends on: none.
- [x] 1.2 Add a single domain helper for deriving stage, next_action, can_generate_solution, and unanswered_question_ids. Depends on: 1.1.
- [x] 1.3 Add tests for new session, partial answer, final answer, generated, saved, adopted, archived, and unknown status. Depends on: 1.2.

## 2. Backend Lab service

- [x] 2.1 Update LabSession response models without changing real Project Radar case selection or local persistence ownership. Depends on: 1.2.
- [x] 2.2 Change answer handling to trim and validate input, preserve unrelated answers, and recompute the workflow contract. Depends on: 2.1.
- [x] 2.3 Add a server-side readiness gate to generate_solution; ensure _solution is not called on a rejected request. Depends on: 2.2.
- [x] 2.4 Enforce explicit save semantics and preserve the distinction between saved, adopted, archived, quality, and publication. Depends on: 2.1.
- [x] 2.5 Add service tests for 404, 409, 422, idempotent re-answer, and durable state persistence. Depends on: 2.2, 2.3, 2.4.

## 3. API and schema

- [x] 3.1 Map domain errors to the existing API error envelope in interfaces/api/routers/projects.py. Depends on: 2.5.
- [x] 3.2 Add response fields and error examples to the API schema/OpenAPI export if the repository export requires regeneration. Depends on: 3.1.
- [x] 3.3 Add API tests for start, answer, generate, save, and explain-node success and failure paths. Depends on: 3.1.

## 4. Frontend contract consumers

- [x] 4.1 Replace open current_stage: string usage with typed known values plus an unknown-safe parser in frontend/src/types/projects.ts. Depends on: 3.1.
- [x] 4.2 Update frontend/src/lib/projects/api.ts return types and mocks for readiness fields and 409 errors. Depends on: 4.1.
- [x] 4.3 Update existing Projects Lab tests so generation follows the server contract and all required questions are answered. Depends on: 4.2.
- [x] 4.4 Add a regression test proving an unknown stage never enables Generate Solution. Depends on: 4.2.

## 5. Verification and handoff

- [x] 5.1 Run targeted backend Lab tests and frontend Projects tests. Depends on: 3.3, 4.4.
- [x] 5.2 Run frontend typecheck, python compile, and the repository smoke gate. Depends on: 5.1.
- [x] 5.3 Record the API contract version and hand off the dependency to research-lab-ai-native-workspace. Depends on: 5.2.
