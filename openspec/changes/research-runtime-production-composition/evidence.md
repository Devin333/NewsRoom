# Research runtime production composition evidence

## 1. Evidence status

This file records replayable evidence for completed slices of the active change. It is not a declaration that the production Research composition is complete.

- Evidence date: `2026-07-19`.
- Slice baseline: branch `main`, adapter baseline `cd6e8f39`, PRD baseline `f799698d`.
- OpenSpec ledger after the bounded-document-RAG slice: `20/46` complete and `26/46` open.
- Settings, sanitized unavailable errors, and composition lifecycle tasks `2.1`-`2.3` are committed in `5effa03e`.
- Source/document adapter tasks `3.1`-`3.6` and GitHub tasks `4.4`-`4.6` were already checked in the initial task ledger although their implementation was not part of `5effa03e`. The adapter commit containing this evidence file closes that traceability gap; the checked state is justified only when the staged-candidate verification in section 3 passes.
- Structured candidate tasks `4.1`-`4.3` are implemented by the schema-bound `StructuredResearchCandidateWorker` and its real `OpenAICompatibleClient` transport integration; their evidence and completion boundary are recorded in sections 2 and 3.
- Bounded-document-RAG tasks `5.1`-`5.4` and `5.6` are implemented by `42f5348e`. Task `5.5` remains open until the same actor and request isolation is proven through the shared production service required by task `2.5`; the direct runtime already has two-run and 50-run isolation regressions.
- Tasks `2.4`-`2.5`, `5.5`, `6.1`-`7.5`, and the final delivery tasks remain separately gated. In particular, valid settings still fail closed until the real production object graph and durable stores exist.

## 2. Adapter requirements and oracles

| Tasks | Production implementation | Primary oracle | Completion boundary |
| --- | --- | --- | --- |
| `3.1`-`3.2` | `ArxivResearchSourceProvider` over the official connector | exact item selection; bounded cache reuse/eviction; URL/id/PDF/version conflict rejection; supported id/abs/PDF/e-print/src aliases; top-level retryability | Does not prove default Research composition shares the process Source provider; Source tasks `3.7`/`3.10` remain open |
| `3.3`-`3.5` | `ResearchDocumentCompilerAdapter` over injected LaTeX/PDF components | LaTeX, PDF, and abstract paths bind `ResearchDocument.source_hash` and lineage to the accepted `PaperSourceRecord`; parser content/package hashes remain separate metadata; typed rate-limit and parser diagnostics contain no raw error text | Does not claim an optional parser runtime is installed or live full text is universally available |
| `3.6` | Concrete adapter and real gate regressions | LaTeX/PDF/abstract outputs pass `ResearchDocumentSchemaGate`; content-type/size failures produce explicit abstract-only gaps without fabricated sections | Live arXiv qualification remains optional and separate |
| `4.4` | `GithubResearchRepositoryAdapter` over `GithubConnector.fetch_repository_metadata()` | response identity validation; stars, forks, watchers, issues, and observation lineage map from distinct real fields; observation clock is distinct from GitHub resource `updated_at` | Missing connector fields remain `None`; they are never copied from another metric |
| `4.5`-`4.6` | paper-card runtime skips GitHub without `code_url` | zero connector calls; absent GitHub fields; bounded `code_repository_missing` diagnostic; canonical paper-card source identity accepts validated arXiv aliases | Does not implement the structured candidate worker or production object graph |
| `4.1`-`4.3` | `StructuredResearchCandidateWorker` over `OpenAICompatibleClient`; `ResearchSinglePaperRuntime` supplies accepted taxonomy evidence; `WorkerRAGPlanner` consumes the same RAG candidate contract | four task-specific schemas with `additionalProperties=false`; strict task allowlist; provider/output error sanitization; evidence/source-scope rejection; bounded prompt projection includes only sanitized `allowed_source_refs`; canonical `RAGScopeGate` rejects missing/mismatched scope, invalid source policy, out-of-scope refs, and `read_source` without refs; real recorded OpenAI-compatible transport passes existing deterministic Research gates | Worker output is candidate data only. Harness remains the authoritative corpus/source/tool/budget/routing/quality gate, and this slice does not compose the default production service |
| `5.1`-`5.4`, `5.6` | `BoundedDocumentRAGRuntime`, `PaperRAGSession.run_spec()`, canonical chunk mapping, durable local BM25 payload store, and local/Qdrant backend selection | supplied session identity/goal/budget/source scope are consumed unchanged; section/span/source/artifact lineage survives chunking and projection; accepted/rejected/conflicting/gap/budget projections are typed; physical chunk ids are run-scoped; local storage validates checksum/file identity and uses process plus OS locks; visibility pagination and Qdrant filters fail closed | Direct runtime and backend contracts are complete. Shared production-service actor propagation and request isolation remain task `2.5`/`5.5`, so this row does not claim the default production graph is ready |

The source identity contract is fail closed: all present identity-bearing fields on a recorded arXiv item (`RawSourceItem.url`, `metadata.arxiv_id`, and `metadata.pdf_url`) must normalize to one exact id before canonical abs/PDF URLs are constructed. An unversioned request may accept one consistently versioned response, but multiple matching versions or any intra-item conflict are rejected.

The document hash contract intentionally separates identity from content integrity:

- `PaperSourceRecord.source_hash` is the accepted source identity hash.
- `ResearchDocument.source_hash` and `ResearchDocument.lineage.source_hash` bind to that accepted hash so deterministic gates can prove continuity.
- parser output hash is retained as `compiled_content_hash`.
- fetched PDF/source package checksum is retained as `source_package_checksum` when present.

## 3. Replayable verification

Pre-staging working-tree checks:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/infrastructure/research/test_source_adapters.py `
  tests/infrastructure/research/test_github_repository.py `
  tests/infrastructure/external/sources/connectors/test_github.py `
  tests/business/research/integration/test_single_paper_loop_fake_runtime.py `
  tests/business/research/code_repository/test_code_repo_models.py `
  tests/architecture/test_infrastructure_boundary.py
```

Observed result: `79 passed`.

Staged-candidate Research adapter/integration check after the final identity and observation-time fixes:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/business/research/integration `
  tests/infrastructure/research `
  tests/infrastructure/external/sources/connectors/test_github.py
```

Observed result in detached staged-only worktree `778f6a1b`: `109 passed, 9 skipped`. The nine skips are optional integration environments and are not counted as production adapter proof.

Additional staged-candidate gates:

```powershell
.\.venv\Scripts\python.exe -m scripts.dev compile
.\.venv\Scripts\python.exe -m scripts.dev smoke
openspec validate research-runtime-production-composition --strict
openspec validate --all --strict
git diff --check
```

Observed results:

- `tests/architecture`: `97 passed, 4 warnings`; warnings are existing FastAPI `on_event` deprecations.
- `python -m scripts.dev compile`: passed.
- mandatory `python -m scripts.dev smoke`: `1203 passed, 23 skipped, 12 warnings`; Source validation reported `is_valid=true` and `error_count=0`.
- `openspec validate research-runtime-production-composition --strict`: passed.
- `openspec validate --all --strict`: `181 passed, 0 failed` in the staged-only tracked snapshot.
- `git diff --check`: passed.

Candidate-worker focused check on the current working tree:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/infrastructure/research/test_candidate_worker.py `
  tests/infrastructure/research/test_candidate_worker_runtime.py
```

Observed result: `25 passed`.

Candidate plus full Harness/Research RAG contract check:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/framework/harness/rag `
  tests/business/research/rag `
  tests/infrastructure/research/test_candidate_worker.py `
  tests/infrastructure/research/test_candidate_worker_runtime.py
```

Observed result: `520 passed`.

Candidate plus Research integration, concrete adapter, and architecture boundary check:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/business/research/integration `
  tests/infrastructure/research `
  tests/architecture/test_infrastructure_boundary.py
```

Observed result: `117 passed, 9 skipped`. The skips are existing optional integration environments and are not counted as candidate-worker proof.

Broader Research compatibility check:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/business/research `
  tests/infrastructure/research
```

Observed result: `770 passed, 23 skipped`. Staged-only compile, mandatory smoke, strict OpenSpec, and whitespace gates are recorded separately before the slice commit; these working-tree checks do not substitute for them.

The complete architecture suite observed `97 passed, 4 warnings`; all warnings are the existing FastAPI `on_event` deprecations.

Bounded-document-RAG working-tree checks after the final identity, scope, pagination, and file-lock fixes:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/business/research/application/test_bounded_document_rag.py `
  tests/business/research/application/test_paper_rag_session.py `
  tests/business/research/rag/test_retrieval_port.py `
  tests/business/research/services/test_tenant_visibility.py `
  tests/framework/harness/rag/test_rag_session_controller.py `
  tests/framework/harness/rag/test_rag_transcript.py `
  tests/infrastructure/research/test_bounded_document_rag_runtime.py `
  tests/infrastructure/research/test_local_chunk_store.py `
  tests/infrastructure/storage/vector/test_paper_chunk_store.py `
  tests/interfaces/composition/test_research_rag_composition.py
.\.venv\Scripts\python.exe -m pytest -q tests/business/research
.\.venv\Scripts\python.exe -m pytest -q tests/infrastructure/research
.\.venv\Scripts\python.exe -m pytest -q `
  tests/framework/harness/rag `
  tests/infrastructure/storage/vector `
  tests/interfaces/composition `
  tests/architecture
```

Observed results: `109 passed`; `743 passed, 23 skipped`; `92 passed`; and `264 passed, 4 warnings`. The warnings are the existing FastAPI `on_event` deprecations.

The final bounded-RAG staged-only candidate `057dd92b` contained exactly the 27 implementation/test files committed as `42f5348e`; unrelated Tool, Workflow, Worker, Redis, API, Source-binding, OpenAPI, quality, and generated files were absent. Candidate gates observed:

- mandatory `python -m scripts.dev smoke`: `1247 passed, 23 skipped, 12 warnings`; Source validation reported `is_valid=true`, `error_count=0`, and `warning_count=0`;
- infrastructure Research/vector/composition matrix: `178 passed`;
- bounded-RAG focused matrix: `109 passed`;
- scoped `ruff check`: passed;
- Research change strict validation: passed;
- repository OpenSpec strict validation: `181 passed, 0 failed`;
- `git diff --check HEAD^ HEAD`: passed.

Independent adversarial review also replayed foreign-user candidate injection and result/transcript terminal-status mismatch. The former produced no accepted evidence and a `source_scope_violation` rejection; the latter failed before projection. Its focused identity/scope regression selection observed `25 passed, 11 deselected`. A separate reader/writer probe held the read-side OS lock while a writer attempted atomic replacement: the reader returned the old consistent snapshot, the writer then committed, and the final payload set contained both records without corruption or deadlock; the local-store suite observed `22 passed`.

Final staged-only code candidate `cffe1bda` was created from the main worktree index with `git write-tree`/`git commit-tree` and verified in a detached worktree. Unstaged Tool, Workflow, Redis, interface, OpenAPI, and other user changes were absent. The candidate gates were:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/framework/harness/rag `
  tests/business/research/rag `
  tests/infrastructure/research/test_candidate_worker.py `
  tests/infrastructure/research/test_candidate_worker_runtime.py
.\.venv\Scripts\python.exe -m pytest -q tests/architecture
.\.venv\Scripts\python.exe -m scripts.dev compile
.\.venv\Scripts\python.exe -m scripts.dev smoke
openspec validate research-runtime-production-composition --strict
openspec validate --all --strict
git diff --check HEAD^ HEAD
```

Observed staged-only results:

- Candidate/Harness RAG: `520 passed`.
- Architecture: `97 passed, 4 warnings`; warnings are existing FastAPI `on_event` deprecations.
- Compile: passed.
- Mandatory smoke: `1207 passed, 23 skipped, 12 warnings`; Source validation reported `is_valid=true`, `error_count=0`, and `warning_count=0`.
- Research change strict validation: passed.
- Repository OpenSpec strict validation: `181 passed, 0 failed` in the tracked staged-only snapshot.
- Candidate whitespace check: passed.

The evidence-result text was added after the code candidate completed. Only this Markdown evidence file changed afterward; final staged strict OpenSpec and whitespace checks are rerun before commit.

## 4. Boundary and compatibility evidence

- `infrastructure/research` imports only exact approved `business.research.domain.*` and `business.research.ports.*` contracts. `tests/architecture/test_infrastructure_boundary.py` enumerates the complete adapter import set; there is no directory-wide `business.*` exception.
- `business/research` has no dependency on `interfaces`, concrete `infrastructure`, or legacy `business/boards/paper_radar` for this slice.
- The local chunk backend implements the business-owned `ChunkPayloadStorePort`; backend selection remains in `interfaces/composition/research.py`, and Qdrant-specific I/O remains in infrastructure. `PaperRAGSession` consumes the supplied domain-neutral Harness session spec but does not own outer workflow routing or publication.
- `business.research.code_repository.models` remains a behavior-free public re-export of the canonical domain models, preserving existing imports without a second DTO implementation.
- Adding optional `GithubRepositoryMetadata.watchers_count` is additive. Missing `subscribers_count` remains `None`; new code does not reinterpret GitHub `stargazers_count` as watchers.
- The paper-card gate compares the card with the previously verified canonical `ResearchPaper`, while the earlier source-lineage gate retains the original requested alias. This preserves request traceability without requiring textual URL equality at every later step.

## 5. Known incomplete work

- No configured production graph exists yet for `ResearchApplicationService -> AnalyzePaperUseCase -> ResearchSinglePaperRuntime`; task `2.4` remains open.
- Durable artifact binding, durable run store, production object graph, entrypoint cutover, and production-composition recorded transport smoke remain open. The bounded RAG and structured candidate adapters are complete but are not a production path until task `2.4` binds them.
- Task `5.5` remains open even though direct runtime `ContextVar` isolation and 50-run tests pass: the production-service scenario still needs actor propagation and shared-factory concurrency evidence under tasks `2.5` and `7.1`-`7.2`.
- Source process ownership and shared arXiv package/PDF ledger evidence remain in `source-policy-contract-convergence` tasks `3.7` and `3.10`.
- This slice does not provide live arXiv/GitHub/LLM readiness evidence and does not supply production on-call, rollback target, observation window, or RTO.

## 6. Stage-20 Research requirement ledger

Each requirement has one accountable task/change owner. Supporting tasks and commits may provide partial evidence but do not independently close the requirement.

| Requirement | Accountable task/change | Current tests/evidence | Implementation commit | Status |
| --- | --- | --- | --- | --- |
| `RES-001` | task `2.4` in this change | configured object-graph and default-entry execution still pending | settings/adapters `5effa03e`, `cd6e8f39`, `7b23a75f`, `42f5348e` | In progress |
| `RES-002` | task `2.4` in this change | typed unavailable tests exist; configured graph exclusion test pending | `5effa03e` plus adapter commits | In progress |
| `RES-003` | task `2.4` in this change | bounded child-session identity is covered; recorded outer workflow binding pending | `42f5348e` | In progress |
| `RES-004` | task `1.2` in this change | precise infrastructure-boundary suite passes; final production graph traversal pending | `cd6e8f39`, `42f5348e` | In progress |
| `RES-005` | task `7.1` in this change | `/ask` and `/rag-ask` shared-factory/mode parity pending | none | Open |
| `RES-006` | task `2.5` in this change | direct runtime tenant/user/source/50-run isolation passes; production actor propagation pending | `42f5348e` | In progress |
| `RES-007` | `research-experience-memory-provenance` task to be created | no durable experience provenance evidence in this change | none | Open, external owner |
| `RES-008` | task `6.6` in this change | restart reconstruction tests pending | none | Open |
| `RES-009` | task `7.2` in this change | interface/service boundary and six-entry parity pending | none | Open |
| `RES-010` | task `7.2` in this change | inbound/outbound MCP dependency and recursion probes pending | none | Open |
| `RES-011` | task `2.5` in this change | composition reset/close exists and RAG state is context-local; shared production graph concurrency pending | `5effa03e`, `42f5348e` | In progress |
