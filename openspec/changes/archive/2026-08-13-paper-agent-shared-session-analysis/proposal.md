## Why

NewsRoom needs a reusable framework-level shared session runtime for multi-agent collaboration. Paper ingest is the first production use case: the final paper analysis path should coordinate specialized business agents through a durable, sanitized, auditable shared session instead of routing all classification through one legacy classifier.

## What Changes

- Add a generic `framework/agent/session` runtime with structured refs/items/events/snapshots, SQLite durable storage, MemoryRuntime bridge storage, in-memory test storage, workspace APIs, sanitization, compaction, lifecycle, access policy, artifact refs, and context assembly.
- Propagate shared session ids through `SubAgentExecutor` and let `AgentLoop` inject assembled session context only when an agent opts into `session_context_policy`.
- Add the final paper radar multi-agent package with structure, selection, taxonomy, experiment, evidence verification, contribution, quality, reproducibility, comparison, profile composer, memory, and reader adapter agents.
- Keep paper-specific semantics in `business/boards/paper_radar/agents`; framework code remains generic and has no paper, business, interface, or provider dependency.
- Make `PaperIngestApplicationService` run the new paper analysis orchestrator as the default official path, with the legacy classifier only as a marked fallback.

## Capabilities

### New Capabilities
- `agent-shared-session`: Framework-level durable shared session runtime for orchestrated multi-agent collaboration.
- `paper-agent-analysis`: Final paper radar multi-agent analysis workflow over the framework shared session runtime.

### Modified Capabilities
- `business-layer-final-target-pipelines`: Paper ingest uses paper agent analysis by default and records legacy classifier fallback when the agent path fails.

## Impact

- Affects `framework/agent/session`, `framework/memory/session`, `framework/agent/subagents/executor.py`, `framework/agent/loop/loop.py`, `framework/agent/models/spec.py`, paper radar business agents, paper ingest configuration, and related tests.
- Adds focused framework, paper business, ingest, and import-boundary tests.
- No new external network dependency is required; SQLite uses the Python standard library.
