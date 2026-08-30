## Context

The repository already provides document parsers, parser cascade quality probing, evidence builders, benchmark models, GitHub observations and durable artifact primitives. The missing boundary is an application-level ingest contract and a typed catalog store that can join those capabilities without coupling `backend/research` to infrastructure.

## Goals / Non-Goals

**Goals:**

- Make source resolution, identity merge, parsing, evidence/chunk/artifact persistence and catalog projection one observable use case.
- Keep all candidate generation separate from deterministic verification and publication.
- Make every result tenant/actor scoped, idempotent and diagnosable.
- Support injected ports for tests and filesystem adapters for the default local runtime.

**Non-Goals:**

- Do not change frontend screens or rewrite existing parser/RAG engines.
- Do not execute repository code or infer runnability from README signals.
- Do not rank unverified benchmark claims or depend on Papers with Code services.

## Decisions

1. **Ports-first boundary.** `ParsePaperUseCase` receives source resolver, parser/compiler, repositories, artifact store and event sink through protocols. Infrastructure adapters implement those protocols; HTTP and CLI call the application facade.
2. **Snapshot before merge.** Every source request is normalized and persisted as a snapshot before identity merge. A merge records match reasons and field conflicts instead of overwriting values.
3. **Bounded synchronous state machine.** The use case emits `received -> resolving -> parsing -> parsed/degraded -> catalog_partial/catalog_ready` (or `metadata_only/failed`) and enforces a finite retry budget. Event writes are append-only and replayable.
4. **Candidate-first catalog.** Extracted relations and scores default to `candidate`. A deterministic compatibility/evidence gate is the only automatic promotion path; conflicting, incomplete or scope-invalid records remain quarantined.
5. **Projection separation.** `ResearchPaperCard` may consume a Catalog query result for display, but typed entities and relations remain the source of truth.
6. **Filesystem durability.** The default repository stores versioned JSON with atomic writes and locking, keyed by tenant and canonical paper id. Adapters may be replaced by database implementations later.

## Risks / Trade-offs

- Generic publisher HTML varies widely; unsupported or denied content intentionally degrades to metadata-only with a reason.
- A conservative identity fingerprint can leave duplicates for ambiguous titles; explicit external ids and diagnostics make later reconciliation safe.
- Synchronous parsing increases request latency; bounded limits and durable run ids leave a clear path to asynchronous scheduling.
