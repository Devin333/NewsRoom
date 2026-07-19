# Research runtime production composition evidence

## 1. Evidence status

This file records the implementation and replayable verification evidence for the active `research-runtime-production-composition` change. It distinguishes an implemented working-tree candidate from a delivered, staged-only commit and from live-provider production readiness.

- Evidence date: `2026-07-19`.
- Current branch/HEAD baseline: `main` at `8693833c`.
- Committed implementation foundations: settings/composition lifecycle `5effa03e`, source/document/GitHub adapters `cd6e8f39`, structured candidate worker `7b23a75f`, and bounded document RAG `42f5348e`.
- Current working-tree OpenSpec ledger: `45/46` complete. Tasks `1.1` through `8.4` are implemented and verified; only task `8.5` remains open for path-scoped staging, staged-only verification, evidence finalization, and commit.
- The working-tree implementation now contains the real production object graph, durable Research run and Harness artifact storage, all six recorded entry surfaces, explicit actor-scope propagation, shared resource lifecycle, and restart-safe parent/child RAG replay.
- The change is not delivered until task `8.5` produces a verified commit containing only this change's owned files. The status of every change-owned Stage-20 Research requirement is therefore `Awaiting delivery`, not `Complete`.
- Live arXiv/LLM execution was not run. Recorded transports prove the concrete adapter/runtime contract without making external calls, but they do not prove that a live provider/model deployment is ready.
- Stage-20 `RES-007` remains owned by the separate `research-experience-memory-provenance` change. This change neither closes nor waives it.

## 2. Implemented requirements and primary oracles

| Tasks | Production implementation | Primary oracle | Boundary |
| --- | --- | --- | --- |
| `1.1`-`2.5` | `interfaces/composition/research.py` composes `ResearchApplicationService -> AnalyzePaperUseCase -> ResearchSinglePaperRuntime` with concrete source, document, candidate, GitHub, RAG, artifact, event, and durable run-store dependencies | Configured object-graph traversal rejects `_UnconfiguredAnalyzeUseCase`, fakes, legacy paper-radar modules, and `InMemoryResearchRunStore`; unavailable configuration resolves lazily to a sanitized typed service | Concrete graph readiness is separate from live external-provider qualification |
| `3.1`-`3.6` | `ArxivResearchSourceProvider` and `ResearchDocumentCompilerAdapter` reuse the approved Source runtime, official connectors, and LaTeX/PDF cascade | Exact item identity; bounded cache; supported id/abs/PDF/e-print/src aliases; conflict rejection; source/package/content hash continuity; real schema gate on LaTeX, PDF, and abstract-only paths | Abstract fallback truthfully records `full_text_sections` as missing and never fabricates structure |
| `4.1`-`4.6` | `StructuredResearchCandidateWorker` and `GithubResearchRepositoryAdapter` use the real OpenAI-compatible and GitHub connector boundaries | Strict task allowlist and schemas; unknown task/malformed JSON/extra fields/foreign evidence fail closed; deterministic gates remain authoritative; absent `code_url` produces no GitHub call or fabricated metrics | LLM output is candidate data only and cannot route, pass quality, authorize, or publish |
| `5.1`-`5.6` | `BoundedDocumentRAGRuntime` maps accepted document sections to scoped chunks, uses the supplied bounded session spec, persists local payloads, and supports optional Qdrant selection | Goal/budget/source/actor scope continuity; accepted/rejected/conflicting/missing projections; local checksum/identity/locking; two-run and 50-run same-paper isolation; recorded replay | `last_context_pack`, run ids, traces, budgets, actors, and source refs are request scoped |
| `6.1`-`6.7` | `FilesystemHarnessArtifactPort`, `ArtifactManager`, `FilesystemResearchRunStore`, and typed `ResearchAnalysisResult.from_dict()` provide durable integrity-protected storage | Context-local run binding; canonical artifact refs and manifests; versioned JSON/checksum/identity/path/regular-file validation; atomic replace and index fault injection; restart reconstruction of analysis, reader, ask, trace, and artifacts | Production truth is durable storage, not a process-global result map |
| `7.1`-`7.4` | HTTP Research, HTTP MCP, local `MCPApplicationService`, stdio MCP, CLI direct MCP, and `NewsMCPServerAdapter` resolve the same managed production provider | One recorded-transport run exercises concrete adapters and Harness; all six query surfaces return the same persisted payload; explicit injected factories still bypass the default provider | Transport loops intentionally differ; composition policy, service contract, actor scope, error semantics, and persistence do not |
| `7.5` | `live_research_e2e` is an explicit opt-in marker and `scripts.dev test-rag-live-e2e` selects every live module | Ordinary pytest/smoke deselects all live modules; the explicit command removes the default exclusion; collection finds 24 live tests | Deselecting or skipping a live test is never production-readiness evidence |
| `8.1`-`8.4` | Focused, broad, architecture, strict OpenSpec, compile, smoke, and whitespace gates were run on the current working tree | Exact commands and results are recorded in section 3 | Staged-only candidate verification and commit remain task `8.5` |

### 2.1 Actor-scope persistence contract

`actor_scope` is an explicit required field in the current v1 Research persistence format. HTTP, MCP, SDK, analysis, summary ask, chunk-RAG ask, trace, transcript, RAG metadata, and durable records carry the same `tenant_id`, `user_id`, and `memory_namespace` projection.

The decoder does not silently upcast a record that lacks `actor_scope`. Missing scope, incomplete scope, or disagreement between the top-level scope and trace/transcript/context projections is corruption and fails closed even if an attacker recomputes the record checksum. Public requests can see only public chunks; a tenant-scoped request can see public chunks plus its own tenant and cannot select another tenant's memory namespace.

### 2.2 Outer Harness and child RAG replay contract

The canonical outer workflow is `research.paper_analysis`. Its recorded execution includes workflow version/checksum, `PLAN -> EXECUTE -> VERIFY` phase boundaries, deterministic gate references, scheduler transitions, and terminal reason. The embedded bounded RAG run is a child session of step `run_research_rag`, not a competing outer controller.

The outer Harness transcript persists `rag_session_refs`, `context_pack_refs`, the child transcript ref, and `parent_run_id`, `parent_workflow_id`, and `parent_step_id`. Reconstruction validates that `ResearchRAGContext` and `RAGContextPack` are both present or both absent and that their run/workflow/step/session/context-pack identities agree. A one-sided projection fails closed. A terminal low-budget RAG halt persists a deterministic `/empty` context-pack ref and gap report, and replay after service reconstruction restores the same child-session and context-pack references.

### 2.3 Source and document identity contract

The source identity contract remains fail closed: all identity-bearing fields on a recorded arXiv item (`RawSourceItem.url`, `metadata.arxiv_id`, and `metadata.pdf_url`) must normalize to one exact id before canonical abs/PDF URLs are constructed. An unversioned request may accept one consistently versioned response, but multiple matching versions or any intra-item conflict are rejected.

The hash contract intentionally separates identity from content integrity:

- `PaperSourceRecord.source_hash` is the accepted source identity hash.
- `ResearchDocument.source_hash` and `ResearchDocument.lineage.source_hash` bind to that accepted hash.
- Parser output hash is retained as `compiled_content_hash`.
- Fetched PDF/source package checksum is retained as `source_package_checksum` when present.

## 3. Replayable verification

All results below are from the current working tree unless explicitly identified as historical committed evidence.

### 3.1 Focused implementation matrix

Concrete Research infrastructure adapters and stores:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/infrastructure/research
```

Observed result: `169 passed, 2 skipped`. Both skips are Windows environments in which the test process could not create the required symlink; the junction regression ran on Windows and is not counted as skipped production proof.

Business application, integration, Research RAG, and Harness RAG:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/business/research/application/test_analyze_paper_use_case.py `
  tests/business/research/application/test_ask_paper_use_case.py `
  tests/business/research/application/test_bounded_document_rag.py `
  tests/business/research/integration/test_single_paper_loop_fake_runtime.py `
  tests/business/research/integration/test_research_actor_isolation.py `
  tests/business/research/rag `
  tests/framework/harness/rag
```

Observed result: `583 passed`.

Production composition, six entry surfaces, service modes, HTTP, MCP, stdio/CLI defaults, and lifecycle:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/interfaces/composition/test_research_composition.py `
  tests/interfaces/composition/test_research_entrypoint_defaults.py `
  tests/interfaces/services/test_research_service.py `
  tests/interfaces/services/test_mcp_application_service.py `
  tests/interfaces/services/test_paper_rag_factory.py `
  tests/interfaces/services/test_paper_rag_service.py `
  tests/interfaces/api/test_research_api.py `
  tests/interfaces/api/test_api_mcp.py `
  tests/interfaces/cli/test_tools_commands.py
```

Observed result: `111 passed`.

Artifact contracts plus architecture boundaries:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/framework/artifacts tests/architecture
```

Observed result: `261 passed, 2 skipped`. The two skips are framework artifact symlink probes that the current Windows environment could not create.

The architecture suite was also run independently:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/architecture
```

Observed result: `102 passed, 4 warnings`. The warnings are existing FastAPI `on_event` deprecations.

### 3.2 Recorded production and replay probes

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/interfaces/composition/test_research_recorded_transport.py
```

Observed result: `2 passed`. The first test executes two real production-composition analyses using recorded arXiv/source and OpenAI-compatible transport responses, then proves parity across HTTP Research, HTTP MCP, local MCP, stdio, CLI, and `NewsMCPServerAdapter`, durable restart reads, artifact integrity, outer workflow identity, gate identity, and parent/child RAG replay. The second test proves that an explicit exhausted RAG replan budget halts deterministically, persists a terminal empty context pack, and replays the same terminal references after reconstruction.

Final focused replay probes observed:

- `tests/business/research/application/test_bounded_document_rag.py`: `36 passed`.
- `tests/business/research/integration/test_single_paper_loop_fake_runtime.py`: `16 passed`.
- `tests/infrastructure/research/test_bounded_document_rag_runtime.py`: `3 passed`.
- `tests/interfaces/composition/test_research_recorded_transport.py`: `2 passed`.

### 3.3 Live-provider offline boundary

The boundary test plus all three live modules under ordinary pytest defaults observed `2 passed, 24 deselected`. The two passing tests prove that every live module carries the opt-in marker and that `scripts.dev test-rag-live-e2e` explicitly selects all of them. A focused live-boundary contract matrix observed `7 passed`, and `pytest --collect-only -m live_research_e2e` found `24 tests`.

No test selected with `-m live_research_e2e` was executed against live arXiv or an LLM. No skip or deselection is cited as provider-readiness evidence.

### 3.4 Broader compatibility matrix

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/business/research
.\.venv\Scripts\python.exe -m pytest -q tests/framework/harness
.\.venv\Scripts\python.exe -m pytest -q tests/interfaces
.\.venv\Scripts\python.exe -m pytest -q tests/framework/artifacts tests/infrastructure/research
```

Observed results, in command order:

- `766 passed, 23 deselected`. The 23 deselections are the marked business Research live modules excluded by the ordinary offline policy.
- `409 passed`.
- `932 passed, 2 skipped, 1 deselected`. The two skips are interface symlink probes unavailable in this environment; the one deselection is the opt-in live production-composition test.
- `328 passed, 4 skipped`. The four skips are the two framework-artifact and two Research-artifact symlink probes unavailable in this environment.

No deselected live test and no unavailable symlink probe is counted as evidence for the behavior it did not execute.

### 3.5 Specification and mandatory repository gates

```powershell
openspec validate research-runtime-production-composition --strict
openspec validate --all --strict
git diff --check
.\.venv\Scripts\python.exe -m scripts.dev compile
.\.venv\Scripts\python.exe -m scripts.dev smoke
```

Observed results:

- Target change strict validation: valid.
- Repository OpenSpec strict validation: `508 passed, 0 failed`.
- `git diff --check`: passed before this evidence refresh and is rerun after it.
- Compile: passed.
- Mandatory smoke: `1304 passed, 23 deselected, 20 warnings`; Source validation reported valid with zero errors. The 23 deselections are opt-in live Research coverage. The warnings are existing FastAPI `on_event` deprecations and do not substitute for live qualification.

Task `8.5` still requires reproducing the applicable gates in a staged-only candidate and verifying that unrelated active OpenSpec, Tool, Workflow, Redis, OpenAPI, and user-owned files are absent before commit.

## 4. Boundary, ownership, and compatibility evidence

- `interfaces/composition/research.py` is the only Research production composition root allowed to join Business ports/use cases to concrete Infrastructure adapters. Default routers, MCP servers, CLI commands, and SDK-facing services call the application service/provider rather than Harness executors or concrete stores.
- `business/research` does not import `interfaces`, concrete `infrastructure`, or legacy `business/boards/paper_radar`. Infrastructure Research adapters are restricted to approved `business.research.domain.*` and `business.research.ports.*` contracts rather than application/services/workflows implementations.
- The MCP inbound server graph and ToolRuntime outbound MCP adapter graph remain separate and acyclic. The six Research entry surfaces share provider policy without sharing transport-global request state.
- `ResearchRuntimeProvider` and `PaperRagRuntimeResources` own process-scoped expensive clients/stores. The vector client is reused across chunk, field, and memory consumers; reranker creation/use is synchronized; `close()` waits for in-flight calls; reset closes the old graph before a new graph becomes visible. There is no independent reranker singleton.
- Actor, run, RAG context, context-pack, artifact binding, and transcript state is run-scoped or context-local. The 50-run same-paper regression found no actor, tenant, document, goal, budget, trace, source-ref, or memory-namespace crossover.
- The local chunk backend is the durable single-host baseline. Optional Qdrant selection is preserved behind the existing port, but this evidence does not claim a live Qdrant deployment was qualified.
- `business.research.code_repository.models` remains a behavior-free public re-export of canonical domain models. This is a compatibility surface, not a second DTO implementation.
- Existing HTTP/MCP response and error shapes remain stable. Configuration/source/gate failures are sanitized consistently, while explicit test factories remain supported injection seams.

### 4.1 Historical adapter evidence retained for traceability

| Commit | Slice | Durable evidence retained |
| --- | --- | --- |
| `5effa03e` | settings and composition lifecycle | Immutable settings, bounded validation, typed unavailable errors, cached provider, and explicit close/reset hooks |
| `cd6e8f39` | source/document/GitHub adapters | Exact arXiv identity, source/document hash separation, truth-preserving abstract fallback, distinct GitHub metric mapping, and no-call behavior without `code_url` |
| `7b23a75f` | structured candidate worker | Four strict task schemas, bounded prompt projection, evidence/source-scope validation, sanitized provider errors, and deterministic gate authority |
| `42f5348e` | bounded document RAG | Canonical chunk lineage, durable local store, optional Qdrant selection, bounded session budgets, context projection, and direct isolation/replay regressions |
| `4113de2d` | prior evidence baseline | Preserves the staged-candidate history for the committed adapter/RAG slices; its earlier partial status is superseded by this current ledger |

These commits are foundations, not a substitute for the uncommitted production composition, durable persistence, actor, lifecycle, entrypoint, and replay work that task `8.5` must deliver together.

## 5. Remaining release boundaries

- Only OpenSpec task `8.5` remains in this change: update/finalize evidence, stage only owned paths and hunks, verify the staged snapshot, and commit. Until then the correct change status is `45/46`, not complete.
- Live arXiv/LLM E2E was not executed because this offline qualification did not use deployment credentials or external services. U7 remains unconfirmed, and no live provider/model is declared ready.
- `RES-007` is intentionally not implemented by this change. Durable `SkillExperience` append/query, real released-package manifest hash, and no-promotion proof remain with `research-experience-memory-provenance`.
- The Source change still owns its own final Research/Harness binding ledger. The shared Source runtime and reservation-ledger object graph here are supporting evidence and do not close another change's tasks by assertion.
- Stage-20 U9 has no operator-provided named on-call, observation window, qualified rollback target, or `max_recovery_time`. This blocks production cutover and a Stage-20 `FINAL` declaration, but it does not block completing this independently verified code change. Those values must not be invented by the implementation team.
- No active OpenSpec change is archived as part of this delivery.

## 6. Stage-20 Research requirement ledger

Each requirement has one accountable task/change owner. Supporting tasks and commits may provide integration evidence but do not independently close the requirement. All requirements owned by this change are implemented in the current working tree and remain `Awaiting delivery` until task `8.5` produces the scoped verified commit.

| Requirement | Accountable task/change | Current tests/evidence | Implementation commit | Status |
| --- | --- | --- | --- | --- |
| `RES-001` | task `2.4` in this change | configured production object graph; recorded HTTP/MCP/CLI six-surface parity; real Harness run | foundations plus current working tree; task `8.5` commit pending | Awaiting delivery |
| `RES-002` | task `2.4` in this change | configured graph excludes unconfigured/fake/in-memory defaults; missing configuration returns sanitized typed unavailable service | foundations plus current working tree; task `8.5` commit pending | Awaiting delivery |
| `RES-003` | task `2.4` in this change | canonical outer workflow; child bounded RAG parent identity, refs, terminal empty pack, and restart replay; one-sided projection fails closed | foundations plus current working tree; task `8.5` commit pending | Awaiting delivery |
| `RES-004` | task `1.2` in this change | precise Business/Infrastructure import boundary and full architecture suite `102 passed` | adapter foundations plus current working tree; task `8.5` commit pending | Awaiting delivery |
| `RES-005` | task `7.1` in this change | `/ask` and `/rag-ask` share injected application factory with explicit mode, actor propagation, lifecycle, and projection-difference regressions | current working tree; task `8.5` commit pending | Awaiting delivery |
| `RES-006` | task `2.5` in this change | explicit actor scope across entry/RAG/trace/transcript/store; tenant visibility; same-paper A/B and 50-run isolation | RAG foundation plus current working tree; task `8.5` commit pending | Awaiting delivery |
| `RES-007` | external `research-experience-memory-provenance` change | no durable experience provenance is claimed by this change | none in this change | Open, external owner |
| `RES-008` | task `6.6` in this change | durable restart reconstruction of analysis, reader, summary ask, chunk-RAG ask, trace, and checksum-bearing artifact refs | current working tree; task `8.5` commit pending | Awaiting delivery |
| `RES-009` | task `7.2` in this change | HTTP/MCP/CLI/default services use the application boundary; AST/import graph rejects direct executor/store access; six-surface recorded parity | current working tree; task `8.5` commit pending | Awaiting delivery |
| `RES-010` | task `7.2` in this change | inbound MCP and outbound ToolRuntime adapter import graph is separate, acyclic, and free of recursive shared request state | current working tree; task `8.5` commit pending | Awaiting delivery |
| `RES-011` | task `2.5` in this change | managed client/store reuse; synchronized reranker; in-flight-aware close; reset-before-rebuild; no unregistered mutable runtime singleton | lifecycle foundation plus current working tree; task `8.5` commit pending | Awaiting delivery |
