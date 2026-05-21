## Context

Phase 1 added frozen intelligence memory objects, deterministic bundle building, optional Postgres persistence, vector indexing compatibility, and a recall skeleton. The current repository query protocol only exposes broad search methods, and Postgres object storage is save-oriented, so duplicate claims, historical timelines, and memory-aware quality/ranking checks cannot yet be implemented against structured storage.

## Goals / Non-Goals

**Goals:**
- Add structured query and mutation protocols for intelligence memory objects.
- Persist claim status history and support timeline queries in Postgres.
- Add deterministic entity resolution, claim consolidation, event building, timeline, recall planning, memory feature, and quality check services.
- Extend ingestion to use the new services while preserving Phase 1 result fields and legacy memory adapters.

**Non-Goals:**
- No Neo4j/Kuzu, LLM extraction, graph reasoning, runner rewrite, background consolidation worker, adaptive policy tuning, or framework memory runtime replacement.
- No hard dependency on Postgres for local/dev ingestion.
- No forced integration into production ranking or quality gate paths beyond callable deterministic services.

## Decisions

- Keep business memory storage behind protocols. Business services depend on query/mutation protocol methods, while Postgres implements them as an optional adapter.
- Consolidate claims deterministically. Duplicate detection uses normalized text and subject/predicate/object equality; contradiction detection uses simple negation markers for matching subject/predicate pairs.
- Build timelines from persisted `memory_events` and relation tables. Event relations remain independent text IDs, avoiding foreign key coupling to legacy claims and evidence rows.
- Preserve vector memory as an index. Qdrant/vector indexing continues to receive final bundle objects but is not treated as the source of truth.
- Keep recall safe without storage. `IntelligenceMemoryRecallService` continues returning an empty context when no query repository is configured.

## Risks / Trade-offs

- Deterministic extraction and contradiction detection are conservative and can miss nuanced cases. Mitigation: expose metadata and history so later phases can add richer models without changing the storage contract.
- Claim consolidation can update existing claims during ingestion. Mitigation: append claim history records whenever status/confidence changes are persisted.
- Postgres query tests use fake connections and SQL assertions, so they validate contract shape rather than live database semantics. Mitigation: keep SQL simple and migration-backed.
- Additional fields in ingestion results can affect exact dict tests. Mitigation: retain all legacy keys and add metadata additively.
