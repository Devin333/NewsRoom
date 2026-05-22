## Why

Phase 2 intelligence memory can now write structured objects and index them semantically, but the business loop still needs final hardening: reindex observability, deeper pipeline coverage, normalized report recall context, and deterministic ranking/quality consumption. This change closes the remaining Phase 2 gaps without adding new runners, graph storage, or LLM extraction.

## What Changes

- Extend memory reindex output with structured counts, metadata, and full ingestion payload while preserving legacy fields.
- Add focused Phase 2 ingestion tests for duplicate claim merge, contradiction history, duplicate event skip, metadata, repository save, and structured vector indexing.
- Add a report memory context service and route daily report writing through it while keeping direct recall service compatibility.
- Keep structured memory ranking explicit and add integration coverage for `MemoryFeatureComputer` consumption.
- Replace ad hoc daily memory quality metadata with `QualityMemoryChecker`-backed deterministic checks.
- Strengthen factory, API/MCP observability, and Postgres timeline/history/relation repository tests.

## Capabilities

### New Capabilities
- `intelligence-memory-phase2-finalization`: Final Phase 2 business-loop behavior for structured memory observability, recall consumption, ranking features, quality checks, and repository coverage.

### Modified Capabilities

## Impact

- Affects memory application service payloads, daily intelligence report writer and quality gate, memory test coverage, and Postgres memory repository tests.
- No breaking changes are intended for legacy `documents_indexed`, `collections`, `document_ids`, `MemoryIngestionService`, vector-only memory, optional Postgres, or existing run paths.
- No Neo4j/Kuzu, LLM extraction, new runner path, background consolidation worker, or framework memory runtime replacement is introduced.
