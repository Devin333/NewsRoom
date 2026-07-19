## Context

`ResearchSinglePaperRuntime` already owns the Harness-controlled single-paper workflow and deterministic Research gates, but the production interfaces never compose it. `create_app()` and every MCP entrypoint currently default to a bare `ResearchApplicationService`, which installs `_UnconfiguredAnalyzeUseCase`; the first analysis request therefore returns 503 regardless of available environment configuration. The runtime also declares six outbound dependencies for which the production tree has incomplete or no concrete Research adapters, and the service stores completed results only in a process-global in-memory map.

The fix must keep `business/research` independent of `interfaces`, concrete `infrastructure`, and legacy `business/boards/paper_radar`. LLMs remain candidate workers only; Harness owns routing and deterministic verification. Source and artifact paths must reuse the repository's hardened fetch, path, checksum, and manifest boundaries. Tests may replace network transports at adapter boundaries but production composition may not select test fakes.

## Goals / Non-Goals

**Goals:**

- Make configured default HTTP and MCP Research analysis reach the real `ResearchSinglePaperRuntime`.
- Provide concrete adapters over existing arXiv, document, LLM, GitHub, bounded RAG, and artifact primitives.
- Make completed Research results queryable after service/process reconstruction.
- Share one production factory and expensive clients per process while preserving explicit test injection.
- Fail with a stable sanitized configuration-unavailable error when required capabilities are absent.

**Non-Goals:**

- Reintroducing legacy paper-radar services or payloads.
- Making live network calls mandatory in the ordinary offline test suite.
- Claiming full-text availability when only real arXiv metadata/abstract can be retrieved.
- Allowing an LLM to choose workflow routing, gate results, publication, memory writes, or skill promotion.
- Building frontend surfaces or a multi-host distributed Research scheduler.

## Decisions

### 1. Interfaces own the production composition root

`interfaces/composition/research.py` exposes `build_research_application_service()` and a process-scoped cached default factory. This is the only layer allowed to import both Business ports/use cases and Infrastructure adapters. It validates settings, constructs shared transports/stores, and returns:

```text
ResearchApplicationService
  -> AnalyzePaperUseCase
  -> ResearchSinglePaperRuntime
       -> ArxivResearchSourceProvider
       -> ResearchDocumentCompilerAdapter
       -> StructuredResearchCandidateWorker
       -> GithubResearchRepositoryAdapter
       -> BoundedDocumentRAGRuntime
       -> FilesystemHarnessArtifactPort
  -> FilesystemResearchRunStore
```

HTTP Research, the MCP application default, CLI MCP, stdio, and `NewsMCPServerAdapter` import the same callable. Existing constructor/factory parameters remain injection seams. The cache has an explicit reset/close hook for tests and process shutdown; request state remains inside run-scoped objects or context-local bindings.

If required LLM configuration is absent or invalid, composition returns a service backed by a typed unavailable use case rather than crashing module import. The error exposes only missing capability names and remediation, never environment values. When configuration is present, the object graph cannot contain `_UnconfiguredAnalyzeUseCase`, `FakeArtifactPort`, test fakes, or the global `InMemoryResearchRunStore`.

Alternatives rejected: composing inside `business/research` reverses dependency direction; constructing the entire graph per request wastes clients and loses persisted query state; keeping the bare service as default preserves the defect.

### 2. Source projection reuses official arXiv connectors

`ArxivResearchSourceProvider` normalizes and validates arXiv identifiers/URLs, calls the existing `ArxivConnector` for real metadata, and projects one exact item into `ResearchPaper`. It retains a bounded thread-safe cache of the fetched paper/source record so `fetch_source_record(paper_id)` refers to the same accepted source. The record contains canonical source URL, fetched time, source hash, arXiv id, abstract/metadata lineage, and optional source/PDF package references; it does not embed unbounded raw bytes.

Unsupported source schemes fail with a typed source error. Recorded XML/source transports used in tests exercise this concrete adapter; they are transport replacements, not fake Research providers.

### 3. Document compilation is real and truth-preserving

`ResearchDocumentCompilerAdapter` first uses the existing arXiv LaTeX compiler and configured PDF cascade against real source bytes. If a supported full-text parser is unavailable or the package cannot be compiled under policy, it may produce an abstract-only `ResearchDocument` from the accepted real metadata. That fallback contains exactly one labeled abstract section, real source refs/hash, compiler diagnostics, and `missing_information=["full_text_sections"]`; it never invents method, experiment, figure, table, equation, or reference content.

Compilation failures that cannot produce even accepted metadata are typed and halt the Harness step. Parser choice and fallback reasons are stored in lineage/diagnostics.

### 4. LLM candidate work is schema-bound and task-specific

`StructuredResearchCandidateWorker` wraps the existing `OpenAICompatibleClient`. It owns prompts and JSON schemas for exactly the candidate tasks currently requested by the single-paper runtime: `candidate_three_minute_read`, `candidate_taxonomy`, and `candidate_experiment_claims`, plus the existing RAG plan candidate contract when configured. Unknown tasks fail closed. Responses are parsed through structured-output validation and projected to the existing Research candidate dictionaries; raw prose or schema-invalid content never reaches domain builders.

Prompts contain bounded real paper/evidence projections and instruct the model to cite only provided evidence ids. Deterministic Research gates remain authoritative after generation. Transport, model, timeout, retry, token, and cost settings come from the shared LLM configuration.

### 5. Missing GitHub is absence, not fabricated repository data

`GithubResearchRepositoryAdapter` parses an actual GitHub repository URL and reuses `GithubConnector.fetch_repository_metadata()` to build `CodeRepositoryProfile` and observations. `ResearchSinglePaperRuntime` calls this port only when the paper has a valid `code_url`; otherwise it passes no GitHub projection to `PaperCardBuilder` and records a bounded `code_repository_missing` diagnostic. It never treats an arXiv URL as a repository and never fills unknown metrics with synthetic zeros.

### 6. RAG runs a bounded session over accepted document chunks

`BoundedDocumentRAGRuntime` converts accepted `ResearchDocument.sections` to canonical `PaperChunk` records with stable ids, section/source refs, spans, and lineage, persists them through a configured local or Qdrant-backed `ChunkStorePort`, and runs `BoundedRAGSessionController`/`PaperRAGSession` using the supplied `RAGSessionSpec` budgets and goal scope. A local filesystem lexical store is the no-DSN single-host backend; Qdrant remains an optional configured backend, not a readiness prerequisite.

The adapter projects `RAGContextPack` candidates into `ResearchEvidenceItem` objects and constructs `ResearchRAGContext` with accepted/rejected/conflicting evidence, gap report, source refs, and session transcript metadata. `last_context_pack` is request-scoped through a context-local or per-run result, not shared mutable global state. No candidate outside the goal's allowed paper/source scope is accepted.

### 7. Harness artifacts and run records are durable and run-scoped

`FilesystemHarnessArtifactPort` adapts Harness `ArtifactWriteRequest` to the hardened `ArtifactManager`. A context-local run binding is established for the duration of `ResearchSinglePaperRuntime.run`; each write uses canonical relative names, atomic JSON bytes, SHA-256, manifest artifact metadata, and the bound run id. Concurrent Research requests cannot exchange run ids. The adapter can read only its canonical `artifact://` references and verifies checksum through the existing store.

`FilesystemResearchRunStore` writes an atomic versioned JSON record under a validated Research storage root. `ResearchAnalysisResult` gains deterministic `from_dict` reconstruction for domain models, Harness trace/transcript, context, diagnostics, and artifact refs. Store reads validate schema, run/paper identity, regular-file/path containment, and checksum before returning a `ResearchRunRecord`. Latest-by-paper uses a small atomic index or a deterministic validated scan; no pickle or unsafe deserialization is used.

The service persists a completed runtime result before returning and can rebuild `get_analysis`, `get_reader`, `ask_paper`, and `get_trace` results after a new service instance is composed.

### 8. Configuration and observability fail safely

`ResearchRuntimeSettings.from_env()` normalizes artifact/research roots, LLM provider/base URL/model/API-key variable, source/parser limits, RAG budgets, and optional vector configuration. It validates paths and required capability presence without reading or logging secret values. Network clients use existing timeouts, retry, rate limit, response-size, robots, and content-type policies.

Composition and runtime emit bounded structured diagnostics for configured/unavailable state, source/compiler/RAG stage, fallback mode, and terminal error class. Public HTTP/MCP errors use the interface safety boundary from `framework-runtime-safety-hardening`; raw prompts, responses, paper content, credentials, and exception text are excluded.

## Risks / Trade-offs

- [Live arXiv/GitHub/LLM services are unavailable] -> bounded retry and typed unavailable/source errors; ordinary tests use recorded transport responses through concrete adapters.
- [Full-text parsers require optional runtimes] -> truth-preserving abstract fallback with explicit gap, never fabricated sections.
- [Shared service handles concurrent requests] -> adapters are immutable or thread-safe; run/artifact/RAG state is request-scoped, context-local, or persisted.
- [Filesystem run index is updated concurrently] -> atomic replace plus lock/compare discipline and checksum validation; PostgreSQL can be a later multi-host adapter.
- [Structured LLM output changes across providers] -> task-specific schemas and deterministic validation/gates fail closed.
- [Local lexical retrieval is mistaken for semantic/vector readiness] -> report backend and retrieval diagnostics explicitly; it is a real bounded single-host baseline, not a claimed Qdrant equivalent.
- [Historic in-memory results are unavailable after cutover] -> no unsafe migration is possible; new results are durable, and existing artifact-backed runs may be imported only through an explicit validated command later.

## Migration Plan

1. Add adapter contracts, settings, production composition tests, and recorded source/LLM fixtures.
2. Implement source/compiler/candidate/GitHub/RAG/artifact adapters behind explicit factory injection.
3. Add JSON result reconstruction and filesystem run store; prove restart reads and concurrent run isolation.
4. Cut HTTP and all MCP defaults to the shared factory while retaining existing explicit test factories.
5. Extend smoke to invoke configured Research composition at recorded adapter boundaries; keep optional credential-gated live E2E separate.
6. Run Research/Harness/architecture/interface suites, mandatory compile/smoke, and strict OpenSpec validation before commit.

Rollback may restore the previous explicit unavailable behavior only as an emergency configuration switch; it must not select fakes or in-memory storage as production. Durable files remain readable and are not deleted during rollback.

## Open Questions

None for implementation start. Multi-host Research scheduling, PostgreSQL run-record storage, and additional non-arXiv source providers require separate changes.
