## 1. Production Composition Regressions

- [x] 1.1 Replace the test that expects the default Research service to be permanently unconfigured with settings-aware configured/unavailable contract tests.
- [x] 1.2 Add production object-graph assertions rejecting `_UnconfiguredAnalyzeUseCase`, Research fakes, `FakeArtifactPort`, legacy paper-radar imports, and `InMemoryResearchRunStore` defaults.
- [x] 1.3 Add recorded arXiv metadata/source and OpenAI-compatible response fixtures at transport boundaries, with no fake Research provider or fake runtime in the composed path.
- [x] 1.4 Add HTTP Research, HTTP MCP, local MCP, stdio, CLI, and `NewsMCPServerAdapter` parity regressions through the production service factory.
- [x] 1.5 Add configuration-unavailable regressions proving module/catalog startup works and execution returns sanitized typed 503 without secret values.
- [x] 1.6 Add filesystem restart, concurrent-run isolation, tamper, non-regular-node, and atomic-replace fault-injection regressions for run records and Harness artifacts.

## 2. Settings And Composition Root

- [x] 2.1 Add immutable `ResearchRuntimeSettings.from_env()` for source, LLM, parser, RAG, artifact, and run-store configuration with path and bounded-limit validation.
- [x] 2.2 Add typed composition/unavailable errors that expose capability names and remediation but never environment values or raw exceptions.
- [x] 2.3 Create `interfaces/composition/research.py` with cached production dependencies, explicit reset/close hooks, and preserved injection seams.
- [x] 2.4 Compose `ResearchApplicationService -> AnalyzePaperUseCase -> ResearchSinglePaperRuntime` with concrete adapters and durable run storage when settings are valid.
- [x] 2.5 Prove shared clients/stores are reused while all run ids, RAG state, artifact bindings, and request data remain concurrency-safe.

## 3. Real Source And Document Adapters

- [x] 3.1 Implement `ArxivResearchSourceProvider` over the official connector with canonical id/URL parsing, bounded cache, exact-item selection, real metadata mapping, source hash, and lineage.
- [x] 3.2 Reject unsupported, ambiguous, missing, or conflicting sources with typed errors before LLM or artifact work.
- [x] 3.3 Implement `ResearchDocumentCompilerAdapter` using configured arXiv LaTeX and PDF cascade components over accepted source bytes.
- [x] 3.4 Implement the truth-preserving real abstract-only fallback with explicit `full_text_sections` gap and no fabricated structure.
- [x] 3.5 Record parser selection, source/PDF checksum, fallback reasons, source refs, and missing-information diagnostics on the `ResearchDocument`.
- [x] 3.6 Add concrete adapter tests for successful full text, abstract fallback, size/content-type failure, invalid source, and lineage stability.

## 4. Structured Candidate And GitHub Adapters

- [x] 4.1 Define bounded prompts and JSON schemas for three-minute read, taxonomy, experiment claims, and existing RAG plan candidates.
- [x] 4.2 Implement `StructuredResearchCandidateWorker` over `OpenAICompatibleClient` with strict task allowlist, structured parsing, safe error mapping, and evidence-id scope validation.
- [x] 4.3 Preserve Harness/deterministic gate authority and add adversarial tests for unknown task, malformed JSON, extra fields, unsupported evidence ids, and prompt-secret exclusion.
- [x] 4.4 Implement `GithubResearchRepositoryAdapter` over `GithubConnector.fetch_repository_metadata()` with real profile/observation mapping and source diagnostics.
- [x] 4.5 Change paper-card construction to skip GitHub lookup when `code_url` is absent and preserve missing repository fields without fabricated metrics.
- [x] 4.6 Add GitHub adapter tests for valid repository metadata, connector failure, non-GitHub URL, and missing-code-url no-call behavior.

## 5. Bounded Document RAG Adapter

- [x] 5.1 Add stable `ResearchDocument` section-to-`PaperChunk` mapping with section/span/source lineage and tenant/run scope.
- [x] 5.2 Implement a durable local single-host chunk payload store and optional existing Qdrant-backed selection without requiring Qdrant for baseline readiness.
- [x] 5.3 Implement `BoundedDocumentRAGRuntime` using `PaperRAGSession`/`BoundedRAGSessionController` and the supplied `RAGSessionSpec` goal, budgets, and allowed source scope.
- [x] 5.4 Project `RAGContextPack` into accepted, rejected, conflicting, and missing `ResearchEvidenceItem` collections with stable ids and scores.
- [x] 5.5 Keep `last_context_pack` request-scoped and add concurrent-run tests proving no document, goal, budget, trace, or source-ref leakage.
- [x] 5.6 Add RAG regressions for relevant evidence, missing required evidence, rejected out-of-scope candidates, budget exhaustion, and deterministic replay of recorded chunks.

## 6. Durable Artifacts And Research Run Store

- [x] 6.1 Implement context-local run binding for `FilesystemHarnessArtifactPort` without shared mutable run id.
- [x] 6.2 Adapt Harness artifact writes/reads to `ArtifactManager` with canonical names, checksum verification, manifest refs, atomic bytes, and typed integrity failures.
- [x] 6.3 Add `ResearchAnalysisResult.from_dict()` and any required typed nested reconstruction without unsafe deserialization or loss of trace/context fields.
- [x] 6.4 Implement `FilesystemResearchRunStore` with validated versioned JSON, content checksum, run/paper identity, regular-file/path containment, atomic replace, and owned-temp cleanup.
- [x] 6.5 Implement a concurrency-safe latest-by-paper index that references only committed run records and survives injected index-write failure.
- [x] 6.6 Cut `ResearchApplicationService` production composition to the durable store and prove `analysis`, `reader`, `ask`, and `trace` work after service reconstruction.
- [x] 6.7 Add run/artifact structured diagnostics with allow-listed fields and no paper content, prompt, credential, path, or raw exception leakage.

## 7. Entrypoint Cutover And Smoke

- [x] 7.1 Change `create_app()` default Research factory and its HTTP MCP composition to the shared production factory while preserving explicit test factories.
- [x] 7.2 Change `MCPApplicationService`, CLI MCP, stdio MCP, and `NewsMCPServerAdapter` defaults to the same factory without import-time live calls.
- [x] 7.3 Keep existing Research API response/error contracts and verify quality-gate failures, source failures, unavailable configuration, and successful runs map consistently across transports.
- [x] 7.4 Extend MCP/Research smoke to execute a configured production-composition analysis through recorded adapter transports rather than checking catalog counts only.
- [x] 7.5 Add an optional credential-gated live arXiv/LLM E2E marker and ensure ordinary offline smoke neither performs live calls nor counts a skip as production proof.

## 8. Verification And Delivery

- [x] 8.1 Run focused source/compiler/candidate/GitHub/RAG/artifact/store/composition/service/API/MCP/stdio tests and architecture boundaries.
- [x] 8.2 Run the broader `tests/business/research`, Harness, interfaces, artifact, and smoke compatibility matrices with skip reasons recorded.
- [x] 8.3 Run `openspec validate research-runtime-production-composition --strict`, `openspec validate --all --strict`, and `git diff --check`.
- [x] 8.4 Run `.\.venv\Scripts\python.exe -m scripts.dev compile` and mandatory `.\.venv\Scripts\python.exe -m scripts.dev smoke`; fix root causes.
- [x] 8.5 Update task evidence, commit with path-scoped staging, and verify no unrelated active OpenSpec or user files are included.
