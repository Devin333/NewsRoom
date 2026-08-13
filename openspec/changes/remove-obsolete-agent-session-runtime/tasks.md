## 1. Retired Contract Surfaces

- [x] 1.1 Remove `AgentSessionContextPolicy` from model definitions, exports, serialization, and ordinary AgentSpec roundtrips. (ASR-FR-002, ASR-FR-006)
- [x] 1.2 Make `AgentSpec.from_dict()` reject the retired `session_context_policy` key with a stable error. (ASR-FR-002, ASR-FR-006)
- [x] 1.3 Remove AgentLoop session imports, constructor collaborators, hidden input handling, and shared-session prompt injection. (ASR-FR-002, ASR-FR-003)
- [x] 1.4 Remove special `session_id` metadata propagation from legacy `SubAgentExecutor` while preserving run/workflow/step correlation. (ASR-FR-003, ASR-FR-004)

## 2. Obsolete Runtime Deletion

- [x] 2.1 Delete `framework/agent/session/**` without compatibility exports, fallback stores, or no-op replacements. (ASR-FR-001, ASR-FR-006)
- [x] 2.2 Delete `framework/memory/session/**` and retain Harness-owned memory authority. (ASR-FR-001, ASR-FR-004, ASR-FR-006)
- [x] 2.3 Delete `tests/framework/agent/session/**` only after replacement behavior and deletion guards exist. (ASR-FR-001)

## 3. Architecture And Regression Guards

- [x] 3.1 Add architecture tests for absent packages/symbols/imports/exports, AgentLoop and AgentRunner signatures, AgentSpec rejection, and no metadata promotion. (ASR-FR-001..003, ASR-FR-006)
- [x] 3.2 Add focused AgentSpec and SubAgentExecutor tests for supported roundtrip and preserved run/workflow correlation. (ASR-FR-002..004)
- [x] 3.3 Prove Harness RAG, Research reading, auth/project, persisted conversation, cursor, compaction, and durable transcript owners remain present and independent. (ASR-FR-004)

## 4. Historical OpenSpec Retirement

- [x] 4.1 Record canonical spec hashes, archive `paper-agent-shared-session-analysis` with `--skip-specs`, and prove canonical hashes are unchanged. (ASR-FR-005)
- [ ] 4.2 Record requirement-level implementation, test, archive, and commit evidence in `evidence.md`. (ASR-FR-001..006)

## 5. Verification

- [x] 5.1 Run focused framework agent, Harness, Research, retained-session, conversation, and architecture tests.
- [x] 5.2 Run `./.venv/Scripts/python.exe -m scripts.dev compile` and fix all source/contract failures.
- [x] 5.3 Run `./.venv/Scripts/python.exe -m scripts.dev smoke` and fix every mandatory gate failure.
- [ ] 5.4 Run `openspec validate remove-obsolete-agent-session-runtime --strict` and `openspec validate --all --strict`, then confirm ASR-FR-001..006 each have implementation, test, archive, and commit evidence.
