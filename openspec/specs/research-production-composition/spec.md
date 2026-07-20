# research-production-composition Specification

## Purpose
Define the single production Research composition root, its shared HTTP/MCP
entrypoint policy, and the real source, document, LLM, repository, RAG, artifact,
and persistence adapters required for a bounded Harness-controlled runtime.
## Requirements
### Requirement: Production Research has one real composition root
The system SHALL provide an interface-owned production factory that composes `ResearchApplicationService`, `AnalyzePaperUseCase`, `ResearchSinglePaperRuntime`, concrete source/document/LLM/GitHub/RAG/artifact adapters, and a durable run store. The configured production object graph SHALL NOT contain an unconfigured use case, test fake, legacy paper-radar dependency, or in-memory-only run store.

#### Scenario: Required configuration is present
- **WHEN** the production Research factory is built with valid source, LLM, parser, RAG, and storage settings
- **THEN** an analysis request reaches the real Harness-controlled single-paper runtime
- **AND** every outbound dependency is a concrete production adapter

#### Scenario: Production object graph is inspected
- **WHEN** architecture tests traverse the factory's service and adapter graph
- **THEN** no `_UnconfiguredAnalyzeUseCase`, `FakeArtifactPort`, Research test fake, or `InMemoryResearchRunStore` is selected

### Requirement: All Research interfaces reuse the production factory
Default HTTP Research, HTTP MCP, local MCP, stdio MCP, CLI MCP, and `NewsMCPServerAdapter` entrypoints SHALL resolve the same production Research service factory and SHALL preserve explicit factory injection for tests.

#### Scenario: HTTP and MCP analyze the same configured paper
- **WHEN** equivalent requests enter HTTP Research and any MCP transport
- **THEN** both traverse the same composition policy and Research runtime contracts
- **AND** return compatible run, paper, quality, artifact, and trace fields

#### Scenario: Test supplies an explicit factory
- **WHEN** a test or embedding host passes a Research service factory
- **THEN** the entrypoint uses that explicit factory without mutating the cached production service

### Requirement: Missing configuration fails as typed unavailability
The production factory SHALL validate required capabilities without exposing secret values. If the real runtime cannot be composed, Research analysis SHALL return a stable sanitized unavailable error identifying missing capability names and remediation rather than installing a fake, returning an unclassified exception, or crashing module import.

#### Scenario: LLM credential capability is absent
- **WHEN** production Research is invoked without a resolvable configured LLM credential
- **THEN** the interface returns a typed retry/configuration-unavailable response
- **AND** no environment value, credential, DSN, or raw exception text appears

#### Scenario: Module imports without optional live services
- **WHEN** API or MCP modules are imported in an offline environment
- **THEN** import and catalog discovery succeed
- **AND** unavailability is evaluated when Research execution is requested

### Requirement: ArXiv source and document adapters preserve real evidence
Production Research SHALL obtain paper metadata and source records through the configured official arXiv connectors and SHALL compile a `ResearchDocument` from accepted source/PDF bytes or real metadata. It SHALL preserve canonical source refs, hashes, fetched time, parser/fallback diagnostics, and missing-information state.

#### Scenario: Full-text source compiles
- **WHEN** the arXiv source package is accepted and a configured compiler succeeds
- **THEN** the document contains only sections and structural data derived from those bytes
- **AND** every section has source lineage to the accepted paper source

#### Scenario: Only metadata and abstract are available
- **WHEN** accepted arXiv metadata exists but no full-text compiler succeeds
- **THEN** the adapter may return an abstract-only document with an explicit `full_text_sections` gap
- **AND** does not invent method, experiment, figure, table, equation, or reference content

#### Scenario: Unsupported source is requested
- **WHEN** a source URL is outside the configured Research provider contract
- **THEN** analysis fails with a typed source error before an LLM, artifact publication, or fake fallback runs

### Requirement: Research LLM workers produce schema-bound candidates only
The production candidate worker SHALL use the configured LLM client with task-specific structured-output schemas for the candidate tasks consumed by `ResearchSinglePaperRuntime`. Unknown tasks and invalid outputs SHALL fail closed, and deterministic Research gates SHALL remain authoritative.

#### Scenario: Candidate output satisfies its schema
- **WHEN** the LLM returns a valid three-minute-read, taxonomy, experiment-claim, or RAG-plan candidate
- **THEN** the adapter projects only the schema-approved fields and supplied evidence references
- **AND** Harness gates decide whether the candidate is accepted

#### Scenario: Candidate invents an unknown evidence id
- **WHEN** structured output cites evidence outside the supplied accepted set
- **THEN** deterministic verification rejects the unsupported claim
- **AND** the LLM cannot override the gate result or publication decision

#### Scenario: Candidate task is unknown
- **WHEN** runtime code requests an unregistered candidate task
- **THEN** the adapter raises a typed contract error before calling the LLM

### Requirement: Repository absence is explicit
The production GitHub adapter SHALL fetch real metadata only for a valid paper `code_url`. A paper without a code repository SHALL preserve absence and SHALL NOT query GitHub with the paper source URL or fabricate repository metrics.

#### Scenario: Paper has a GitHub code URL
- **WHEN** the connector returns accepted repository metadata
- **THEN** the adapter builds a `CodeRepositoryProfile` with real values and observation lineage

#### Scenario: Paper has no code URL
- **WHEN** paper card construction runs without a repository URL
- **THEN** GitHub fields remain absent and diagnostics record `code_repository_missing`

### Requirement: Research RAG is bounded and document-scoped
The production RAG adapter SHALL derive canonical chunks from the accepted `ResearchDocument`, execute a bounded Harness RAG session using the supplied session spec, enforce allowed paper/source scope, and project accepted, rejected, conflicting, and missing evidence into `ResearchRAGContext`.

#### Scenario: Document contains relevant sections
- **WHEN** the bounded session retrieves accepted document chunks
- **THEN** each accepted evidence item carries stable evidence id, section/span or artifact reference, source refs, score, and lineage
- **AND** the resulting context obeys the session budget and allowed source scope

#### Scenario: Required evidence is absent
- **WHEN** the document cannot support a required evidence type
- **THEN** the gap report records the missing information and rejected reasons
- **AND** the adapter does not synthesize evidence to satisfy a gate

#### Scenario: Concurrent Research runs execute
- **WHEN** two runs use the shared production service concurrently
- **THEN** RAG context packs, budgets, traces, chunks, and run identifiers remain isolated
