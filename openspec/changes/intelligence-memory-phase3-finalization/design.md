## Context

Phase 3 already added the memory evolution building blocks: graph projection, historical context, historian analysis, memory evaluation, dry-run consolidation, feedback ingestion, and policy proposal generation. The remaining gap is that these capabilities are not consistently exposed through application services, worker helpers, daily workflow metadata, or observable summaries.

## Goals / Non-Goals

**Goals:**
- Expose Phase 3 memory evolution through stable worker, workflow, and interface service boundaries.
- Keep historian output advisory and prompt-safe for report writing and quality metadata.
- Provide graph projection summaries without adding graph-specific persistence.
- Add focused tests plus one minimal Phase 3 loop integration test.

**Non-Goals:**
- No Neo4j/Kuzu dependency.
- No Phase 2 ingestion, recall, vector, or Postgres source-of-truth replacement.
- No API router or CLI command in this pass.
- No automatic high-risk policy proposal application.

## Decisions

- Consolidation worker helpers remain in `business/workers/memory_consolidation_handler.py`; `parse_memory_consolidation_task()` is public for testing and consistent payload handling.
- Historian report consumption uses a small adapter instead of coupling ReportWriter directly to `HistoricalContextService`; this keeps the writer compatible with the existing `ReportMemoryContextService`.
- Quality gate integration reads historian metadata from the draft/memory payload and records it alongside memory quality output. Historian contradictions do not hard-block unless existing memory quality logic already creates a critical issue.
- Interface services wrap business services and return simple dataclass results with `to_dict()`; env factories use the existing memory repository env rules.
- Graph projection remains read-time and summarized from `GraphMemoryService` expansion output.

## Risks / Trade-offs

- Historian metadata depends on writer output wiring -> tests cover deterministic and LLM-request metadata paths.
- Env factories are optional -> when Postgres memory is not configured they return `None` rather than creating sinkless services.
- Graph projection can be incomplete if repository query methods are incomplete -> summaries expose counts and metadata rather than pretending to persist a full graph.
