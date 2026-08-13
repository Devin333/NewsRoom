## Context

The framework has agent loops, sub-agent execution, and memory runtime primitives, but it previously lacked a durable, generic blackboard-style shared session runtime. Paper ingest also needed a final multi-agent analysis chain that can reuse taxonomy and public paper contracts without embedding paper semantics in framework code.

The final design must preserve dependency direction:

- `business -> framework`
- `interfaces -> business/framework`
- `framework -> no business/interfaces/paper concepts`

## Goals / Non-Goals

**Goals:**
- Provide a framework-owned shared session runtime with durable SQLite storage, MemoryRuntime bridge, event log, snapshots, compaction, access policy, lifecycle, workspace API, and prompt context assembly.
- Integrate shared session propagation into `SubAgentExecutor` and opt-in session context injection into `AgentLoop`.
- Implement the final deterministic paper analysis workflow with all paper sub-agents named in the PRD.
- Make paper ingest default to the new agent orchestrator and keep the legacy classifier only as a marked fallback.
- Ensure raw `full_text`, raw payloads, tokens, API keys, and similar sensitive fields never persist into shared session content.

**Non-Goals:**
- Add external vector, Redis, or provider dependencies to the framework session runtime.
- Let paper sub-agents directly read/write the workspace or call each other.
- Make `InMemoryAgentSessionStore` the production paper orchestrator default.
- Disable the final paper agent architecture with a `use_agent_analysis=False` style flag.

## Decisions

- `AgentSharedWorkspace` is the recommended write/read entrypoint for orchestrators.
  - Rationale: centralizes validation, sanitization, access policy, event logging, and compaction decisions.
- `SQLiteAgentSessionStore` is the durable store used by default for paper ingest.
  - Rationale: production paths need process-restart persistence and session isolation without adding third-party dependencies.
- `InMemoryAgentSessionStore` remains available for unit tests.
  - Rationale: fast deterministic tests should not require a durable file.
- `MemoryRuntimeAgentSessionStore` and `framework/memory/session` bridge session items/snapshots into long-term memory.
  - Rationale: comparison and memory agents need historical recall without every sub-agent calling MemoryRuntime directly.
- Paper sub-agents receive `PaperAgentContext` and return `PaperAgentResult`.
  - Rationale: the orchestrator owns ordering, workspace reads, writes, and events.
- Full text may be an agent input but is not stored as raw shared session content.
  - Rationale: session content must be safe for downstream prompt assembly and memory.
- Legacy classifier fallback is marked with `analysisSource="legacy_classifier"`, `legacyFallback=True`, warnings, and prompt memory.
  - Rationale: fallback should be observable without pretending it is the final architecture.

## Risks / Trade-offs

- Deterministic agents can miss nuanced paper claims; the workflow mitigates this through low-confidence items, review queue items, and fallback.
- SQLite is local durable storage, not distributed coordination; future distributed stores can implement the same protocol.
- AgentLoop session injection is opt-in by policy to avoid changing unrelated agents.
- Paper reader enhancement is adapter-based so existing reader/citation/backfill behavior remains compatible.

## Migration Plan

1. Add and test framework shared session runtime.
2. Add MemoryRuntime bridge and session serializers.
3. Wire SubAgentExecutor and AgentLoop.
4. Implement all final paper agents and orchestrator workflow.
5. Switch paper ingest to default agent analysis with SQLite sessions and legacy fallback.
6. Add framework, paper, ingest, and import-boundary tests.
7. Validate OpenSpec and run compile/project tests.

## Open Questions

None for this implementation pass.
