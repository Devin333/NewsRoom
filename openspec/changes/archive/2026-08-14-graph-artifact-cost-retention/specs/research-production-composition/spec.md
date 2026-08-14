## MODIFIED Requirements

### Requirement: Production Research has one real composition root
The system SHALL provide an interface-owned production factory that composes `ResearchApplicationService`, `AnalyzePaperUseCase`, `ResearchSinglePaperRuntime`, concrete source/document/LLM/GitHub/RAG/artifact adapters, a durable run store, an explicitly supplied validated `GraphArtifactPersistenceConfig`, a real artifact catalog, one durable result/quota/cache/usage/GC ledger, one filesystem Graph artifact lifecycle adapter, one `ResultMaterializer`, a graph result committer, an artifact context load planner/loader, and one `GraphArtifactGovernanceRuntime`. The configured production object graph SHALL NOT contain an unconfigured use case, test fake, legacy paper-radar dependency, in-memory-only run/result/governance store, implicit graph artifact policy global, fake graph artifact/catalog/context/governance store, or second artifact body store.

#### Scenario: Required configuration is present
- **WHEN** the production Research factory is built with valid source, LLM, parser, RAG, storage, graph artifact persistence, quota, retention, and governance settings
- **THEN** an analysis request reaches the real Harness-controlled single-paper runtime
- **AND** every outbound dependency is a concrete production adapter
- **AND** the selected graph artifact policy version, rollout mode, quota limits, retention, and alert thresholds are available as one immutable runtime settings snapshot
- **AND** enforce mode commits common result lineage and durable usage while context reads require an approved accounted load plan
- **AND** operator governance operations resolve the same catalog, result database, and physical artifact root

#### Scenario: Production object graph is inspected
- **WHEN** architecture tests traverse the factory's service, settings, materializer, context, and governance adapter graph
- **THEN** no `_UnconfiguredAnalyzeUseCase`, `FakeArtifactPort`, Research test fake, `InMemoryResearchRunStore`, in-memory result quota/cache/attempt/usage/GC store, implicit graph artifact policy lookup, fake durable graph artifact store, or duplicate physical artifact store is selected

#### Scenario: Graph artifact configuration is invalid
- **WHEN** production Research receives unsupported rollout mode, policy version, threshold, run/tenant/class quota, context limit, TTL, retention, alert, catalog, result-store, or GC settings
- **THEN** composition fails with typed sanitized configuration unavailability before a run or governance mutation starts

#### Scenario: Read-only governance is composed
- **WHEN** production selects `read_only`
- **THEN** replay, inspection, context read accounting, GC planning, reports, alerts, and reconciliation use real durable adapters while materialization and physical GC apply remain disabled
