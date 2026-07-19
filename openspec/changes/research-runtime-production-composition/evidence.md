# Research runtime production composition evidence

## 1. Evidence status

This file records replayable evidence for completed slices of the active change. It is not a declaration that the production Research composition is complete.

- Evidence date: `2026-07-19`.
- Slice baseline: branch `main`, `HEAD 4c1d7aaa`.
- OpenSpec ledger before this slice: `12/46` complete and `34/46` open.
- Settings, sanitized unavailable errors, and composition lifecycle tasks `2.1`-`2.3` are committed in `5effa03e`.
- Source/document adapter tasks `3.1`-`3.6` and GitHub tasks `4.4`-`4.6` were already checked in the initial task ledger although their implementation was not part of `5effa03e`. The adapter commit containing this evidence file closes that traceability gap; the checked state is justified only when the staged-candidate verification in section 3 passes.
- Tasks `2.4`-`2.5`, `4.1`-`4.3`, `5.1`-`7.5`, and the final delivery tasks remain separately gated. In particular, valid settings still fail closed until the real production object graph and durable stores exist.

## 2. Adapter requirements and oracles

| Tasks | Production implementation | Primary oracle | Completion boundary |
| --- | --- | --- | --- |
| `3.1`-`3.2` | `ArxivResearchSourceProvider` over the official connector | exact item selection; bounded cache reuse/eviction; URL/id/PDF/version conflict rejection; supported id/abs/PDF/e-print/src aliases; top-level retryability | Does not prove default Research composition shares the process Source provider; Source tasks `3.7`/`3.10` remain open |
| `3.3`-`3.5` | `ResearchDocumentCompilerAdapter` over injected LaTeX/PDF components | LaTeX, PDF, and abstract paths bind `ResearchDocument.source_hash` and lineage to the accepted `PaperSourceRecord`; parser content/package hashes remain separate metadata; typed rate-limit and parser diagnostics contain no raw error text | Does not claim an optional parser runtime is installed or live full text is universally available |
| `3.6` | Concrete adapter and real gate regressions | LaTeX/PDF/abstract outputs pass `ResearchDocumentSchemaGate`; content-type/size failures produce explicit abstract-only gaps without fabricated sections | Live arXiv qualification remains optional and separate |
| `4.4` | `GithubResearchRepositoryAdapter` over `GithubConnector.fetch_repository_metadata()` | response identity validation; stars, forks, watchers, issues, and observation lineage map from distinct real fields; observation clock is distinct from GitHub resource `updated_at` | Missing connector fields remain `None`; they are never copied from another metric |
| `4.5`-`4.6` | paper-card runtime skips GitHub without `code_url` | zero connector calls; absent GitHub fields; bounded `code_repository_missing` diagnostic; canonical paper-card source identity accepts validated arXiv aliases | Does not implement the structured candidate worker or production object graph |

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

## 4. Boundary and compatibility evidence

- `infrastructure/research` imports only exact approved `business.research.domain.*` and `business.research.ports.*` contracts. `tests/architecture/test_infrastructure_boundary.py` enumerates the complete adapter import set; there is no directory-wide `business.*` exception.
- `business/research` has no dependency on `interfaces`, concrete `infrastructure`, or legacy `business/boards/paper_radar` for this slice.
- `business.research.code_repository.models` remains a behavior-free public re-export of the canonical domain models, preserving existing imports without a second DTO implementation.
- Adding optional `GithubRepositoryMetadata.watchers_count` is additive. Missing `subscribers_count` remains `None`; new code does not reinterpret GitHub `stargazers_count` as watchers.
- The paper-card gate compares the card with the previously verified canonical `ResearchPaper`, while the earlier source-lineage gate retains the original requested alias. This preserves request traceability without requiring textual URL equality at every later step.

## 5. Known incomplete work

- No configured production graph exists yet for `ResearchApplicationService -> AnalyzePaperUseCase -> ResearchSinglePaperRuntime`; task `2.4` remains open.
- Structured candidate worker, bounded RAG adapter, durable artifact binding, durable run store, entrypoint cutover, and recorded transport smoke remain open.
- Source process ownership and shared arXiv package/PDF ledger evidence remain in `source-policy-contract-convergence` tasks `3.7` and `3.10`.
- This slice does not provide live arXiv/GitHub/LLM readiness evidence and does not supply production on-call, rollback target, observation window, or RTO.
