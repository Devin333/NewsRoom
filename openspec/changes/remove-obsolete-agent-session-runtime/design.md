## Context

`framework/agent/session` was introduced as a generic mutable blackboard with InMemory/SQLite/MemoryRuntime stores, access policy, lifecycle events, compaction, context assembly, and an AgentLoop prompt hook. Live-tree inventory shows no production consumer outside that package: only `AgentSpec`, `AgentLoop`, and legacy `SubAgentExecutor` expose integration surfaces, while all store/workspace callers are dedicated tests. Phase A now provides the accepted Harness-owned replacements for subagent context, transcript durability, TaskPlan lifecycle/replay, and memory authority.

The cleanup must distinguish the obsolete shared-session state plane from independently owned concepts such as Harness RAG sessions, Research reader sessions, auth/project sessions, persisted conversations, cursors, and conversation compaction. The old completed OpenSpec change is historical evidence only and must not be synced into canonical specs.

## Goals / Non-Goals

**Goals:**

- Delete the obsolete packages, tests, exports, model field, AgentLoop hook, and special subagent metadata propagation.
- Make stale `session_context_policy` input fail explicitly instead of silently becoming a no-op.
- Prevent AgentRunner or another compatibility facade from recreating the shared-session state plane.
- Preserve run/workflow/step correlation and all independently owned session/conversation capabilities.
- Preserve the old OpenSpec artifacts as superseded history without changing canonical specs.

**Non-Goals:**

- Do not delete fields or APIs merely because they are named `session_id`.
- Do not change Harness RAG, context, memory, TaskPlan, durable transcript, conversation cursor, or conversation compaction behavior.
- Do not migrate unused `SQLiteAgentSessionStore` data into a new compatibility store.
- Do not add a feature flag, no-op store, deprecated re-export, or hidden fallback.

## Decisions

### 1. Delete the state plane as one ownership unit

Delete `framework/agent/session/**`, `framework/memory/session/**`, and `tests/framework/agent/session/**` together. Keeping only a model, serializer, in-memory fake, or re-export would retain a second ownership vocabulary and make reintroduction easy.

Alternative considered: repair access policy, sanitization, lifecycle, and compaction gaps. Rejected because those semantics are already owned by Harness and repair would formalize a competing control plane with no production consumer.

### 2. Remove integration surfaces rather than deprecating them

Remove `AgentSessionContextPolicy`, `AgentSpec.session_context_policy`, `AgentLoop.session_workspace`, `AgentLoop.session_context_assembler`, `_agent_session_workspace`, and `_session_context_for_llm`. `AgentSpec.from_dict()` explicitly rejects the retired `session_context_policy` key so stale configuration cannot appear accepted while doing nothing.

AgentRunner remains unchanged except for architecture tests proving that neither its constructor nor `run()` accepts a session store/workspace. There is no compatibility keyword sink.

### 3. Remove only shared-session propagation from legacy subagents

`SubAgentExecutor._child_inputs()` stops copying `session_id` from metadata. It continues to propagate `run_id` and `workflow_id`, and the runner continues to carry `run_id`, `step_id`, workflow checkpoint, trace, conversation, and budget context through their existing owners. A caller-provided ordinary input named `session_id` remains ordinary task data; it is not interpreted or injected by framework code.

### 4. Lock the deletion boundary with source-level tests

Architecture tests assert that both package directories are absent, retired symbols/tokens do not occur in production Python, `AgentSpec` neither emits nor accepts the old policy, AgentLoop/AgentRunner signatures expose no shared-session collaborators, and `_child_inputs()` does not promote metadata `session_id`. The same suite asserts that representative RAG, reading, auth/project, and conversation modules still exist.

### 5. Archive old OpenSpec history without spec sync

After implementation and replacement regressions pass, archive `paper-agent-shared-session-analysis` using `openspec archive paper-agent-shared-session-analysis --skip-specs --yes`. Record canonical spec checksums before and after the command and require equality. The new cleanup change is normally archived so its `legacy-runtime-cleanup` requirements become canonical.

## Risks / Trade-offs

- [Unknown external caller imports a deleted package] -> This is an intentional breaking cleanup; live tracked-source inventory is zero and no compatibility layer is allowed.
- [Generic `session_id` is accidentally removed from another domain] -> Delete only exact packages/symbols and the one metadata propagation branch; add retained-capability source and regression checks.
- [Stale AgentSpec JSON is silently accepted] -> Reject the exact retired key with a stable validation error.
- [Old OpenSpec pollutes canonical specs] -> Archive only with `--skip-specs` and compare canonical spec hashes before and after.
- [Rollback restores an unsafe second control plane] -> Revert Phase B as a unit only for emergency source compatibility; do not alter Phase A durable transcript wiring or add fake fallbacks.

## Migration Plan

1. Commit this Phase B proposal after Phase A replacement acceptance.
2. Remove integration surfaces and obsolete packages/tests; add architecture and focused contract tests.
3. Run agent, Harness, Research, retained session/conversation, architecture, compile, and mandatory smoke gates.
4. Archive `paper-agent-shared-session-analysis` with `--skip-specs` and verify canonical hashes are unchanged.
5. Record requirement evidence and normally archive this cleanup change.

## Open Questions

None. The live-tree consumer inventory, replacement owner, and historical archive mode are resolved.
