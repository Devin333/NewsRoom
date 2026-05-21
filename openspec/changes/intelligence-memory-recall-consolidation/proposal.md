## Why

Phase 1 introduced structured intelligence memory objects, but the memory layer is still mostly write-oriented. NewsRoom needs deterministic recall, consolidation, timelines, and memory-derived quality/ranking signals so later report generation and evaluation paths can inspect durable historical context.

## What Changes

- Add repository query and mutation protocols for structured intelligence memory recall and consolidation.
- Add claim history records and PostgreSQL claim history persistence.
- Add deterministic entity resolution, claim consolidation, event building, and timeline services.
- Extend intelligence recall with a planner, timeline-aware context, and conflict detection while preserving safe empty recall when no query repository exists.
- Add deterministic memory ranking features and quality memory checks as callable business services.
- Extend intelligence ingestion to resolve entities, consolidate claims, build events, save the final bundle, and retain legacy ingestion result fields.

## Capabilities

### New Capabilities
- `intelligence-memory-recall-consolidation`: Recall, consolidate, timeline, rank, and quality-check structured intelligence memory objects.

### Modified Capabilities
- `storage-memory-final-target-closure`: PostgreSQL-backed intelligence memory gains query, mutation, timeline, and claim history support while preserving vector memory behavior.

## Impact

- Affects business memory models, repository protocols, recall/ingestion services, Postgres intelligence memory repository, migrations, and memory tests.
- No breaking change is intended for legacy `MemoryIngestionService`, vector indexing, RunApplicationService integration, or framework memory runtime.
- No graph database, LLM extraction, new runner path, background consolidation worker, or framework evolution module is introduced.
