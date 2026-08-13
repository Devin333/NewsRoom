## 1. OpenSpec

- [x] 1.1 Update proposal, design, specs, and tasks for the ultimate PRD scope.
- [x] 1.2 Validate the change with `openspec validate paper-agent-shared-session-analysis --strict`.

## 2. Framework Shared Session Runtime

- [x] 2.1 Add generic session models, query, artifact refs, role constants, exceptions, sanitization, store protocol, workspace, assembler, access policy, compaction, and lifecycle manager.
- [x] 2.2 Add `SQLiteAgentSessionStore` for durable sessions.
- [x] 2.3 Add `MemoryRuntimeAgentSessionStore` and `framework/memory/session` bridge serializers/adapters.
- [x] 2.4 Keep `InMemoryAgentSessionStore` for tests and compatibility.
- [x] 2.5 Propagate `session_id`, `run_id`, and `workflow_id` through `SubAgentExecutor` without overriding existing inputs.
- [x] 2.6 Add `AgentSessionContextPolicy` and `AgentLoop` shared session context injection.
- [x] 2.7 Add framework tests for stores, workspace, sanitization, assembler, access policy, compaction, lifecycle, SubAgentExecutor propagation, and AgentLoop injection.

## 3. Paper Business Analysis

- [x] 3.1 Keep taxonomy constants and normalization canonical in the paper business layer with interface re-export compatibility.
- [x] 3.2 Add final paper agent roles, models, base protocol, and helpers.
- [x] 3.3 Implement structure, selection, taxonomy, experiment, evidence verification, contribution, quality, reproducibility, comparison, profile composer, memory, and reader adapter agents.
- [x] 3.4 Implement final `PaperAnalysisOrchestrator` workflow through `AgentSharedWorkspace`.
- [x] 3.5 Prevent raw `full_text`, `raw_payload`, tokens, API keys, and similar sensitive fields from being written to shared session content.
- [x] 3.6 Add paper agent tests for final workflow ordering, session sharing, isolation, redaction, benchmark claim verification, quality verification dependency, reproducibility warning, memory warning, profile compatibility, and reader adapter output.

## 4. Ingest Integration

- [x] 4.1 Remove the final-architecture disabling `use_agent_analysis` path.
- [x] 4.2 Add final config fields for legacy fallback, session store path, and agent analysis requirement.
- [x] 4.3 Make paper ingest run `PaperAnalysisOrchestrator` by default.
- [x] 4.4 Use `SQLiteAgentSessionStore` for the default paper orchestrator.
- [x] 4.5 Keep legacy classifier only as marked fallback with prompt memory and classification warnings.
- [x] 4.6 Add ingest tests for default agent path, legacy fallback marking, final profile fields, old reader/citation/backfill compatibility, and final config parsing.

## 5. Boundaries

- [x] 5.1 Add tests that framework session has no business/interface/paper imports or terms.
- [x] 5.2 Add tests that paper agents do not define session stores or import sqlite.
- [x] 5.3 Add tests that paper sub-agent files do not import each other.

## 6. Validation and Commit

- [x] 6.1 Run OpenSpec validation.
- [x] 6.2 Run focused framework, paper, ingest, and import-boundary tests.
- [x] 6.3 Run compile and project test commands.
- [x] 6.4 Commit code changes without unrelated `scripts/test_model_api.py`.
