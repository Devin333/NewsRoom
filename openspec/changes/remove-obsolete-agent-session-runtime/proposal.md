## Why

Phase A has replaced the only claimed replay/audit value of the old mutable agent session plane with Harness-owned durable subagent transcripts, context boundaries, TaskPlan lifecycle events, and memory authority. Keeping `framework/agent/session` now creates an unused second control plane whose access, lifecycle, compaction, prompt injection, and memory semantics conflict with Harness ownership.

## What Changes

- **BREAKING** Delete `framework/agent/session`, `framework/memory/session`, and the tests dedicated to those obsolete packages.
- **BREAKING** Remove `AgentSessionContextPolicy` from `AgentSpec` and remove the `session_workspace` and hidden `_agent_session_workspace` injection paths from `AgentLoop`.
- Remove special `session_id` propagation from the legacy `SubAgentExecutor` while preserving ordinary `run_id`, `workflow_id`, `step_id`, trace, checkpoint, conversation, and budget correlation.
- Add architecture guards that reject reintroduction through compatibility exports, fallback stores, no-op implementations, AgentLoop hooks, or AgentRunner parameters.
- Preserve Harness RAG sessions, Research reading sessions, authentication/project sessions, conversation cursor/compaction, and other independently owned domain concepts that happen to use the word `session`.
- Archive `paper-agent-shared-session-analysis` as superseded history with `--skip-specs` so its obsolete requirements never enter canonical specs.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `legacy-runtime-cleanup`: Retire the obsolete agent shared-session state plane after replacement acceptance, forbid compatibility/runtime fallback, and preserve independently owned session capabilities.

## Impact

- Deleted runtime code: `framework/agent/session/**`, `framework/memory/session/**`.
- Changed contracts: `framework/agent/models/spec.py`, `framework/agent/models/__init__.py`, `framework/agent/loop/loop.py`, and `framework/agent/subagents/executor.py`.
- Deleted/replaced tests: `tests/framework/agent/session/**`; new architecture and retained-capability regression tests.
- Historical OpenSpec: `paper-agent-shared-session-analysis` is archived without syncing its delta specs.
- No persistence migration is provided because the deleted stores have no production consumers and are not an accepted durability source.
