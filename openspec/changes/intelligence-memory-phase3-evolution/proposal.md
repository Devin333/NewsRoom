## Why

Phase 2 made structured intelligence memory writable, searchable, and consumable, but NewsRoom still lacks an explainable graph view, historical analysis, memory quality evaluation, periodic cleanup, feedback learning, and adaptive policy proposals. Phase 3 adds those capabilities without replacing Postgres, vector memory, runner paths, or framework runtime behavior.

## What Changes

- Add graph memory dataclasses, a graph port, a graph service, and a Postgres-backed read-through graph projection over existing memory tables.
- Add deterministic historical context and historian agent services for topic/entity/event/claim analysis.
- Add memory metrics and evaluator services for memory quality reports.
- Add dry-run-first memory consolidation service and worker handler.
- Extend existing feedback memory support with formal feedback objects, feedback ingestion, preference learning, adaptive thresholds, and policy proposal generation.
- Export the new memory APIs and add focused unit tests for every Phase 3 module.

## Capabilities

### New Capabilities
- `memory-evolution`: Graph intelligence memory, historian analysis, memory evaluation, consolidation, feedback learning, and adaptive policy proposals.

### Modified Capabilities

## Impact

- Affects business memory modules, business worker handlers, a new storage graph adapter package, and targeted tests.
- No breaking changes are intended for Phase 2 ingestion, recall, writer, ranking, quality gate, vector indexing, or Postgres repository behavior.
- No Neo4j/Kuzu dependency, no new graph migration, no framework runtime rewrite, and no automatic high-risk policy application is introduced.
