## Context

The current baseline has structured memory objects, Postgres persistence, vector indexing, Recall v2, writer/ranking/quality consumption, and reindex observability. Phase 3 is an additive business-memory layer that interprets those objects as a graph, evaluates memory health, performs deterministic dry-run consolidation, records feedback as memory, and proposes policy changes for human review.

## Goals / Non-Goals

**Goals:**
- Project existing `Evidence / Claim / Entity / Event / Decision / Preference` records into graph nodes and edges.
- Provide deterministic historical context and historian output without LLM dependency.
- Compute memory quality metrics and generate evaluation reports.
- Provide dry-run consolidation tasks and a worker-compatible handler.
- Convert feedback into preference/decision memory and generate policy proposals.

**Non-Goals:**
- No Neo4j/Kuzu hard dependency and no new graph schema migration.
- No replacement of Postgres structured truth or Qdrant semantic indexing.
- No framework worker/runtime rewrite and no new runner path.
- No automatic application of high-risk policy changes.

## Decisions

- `PostgresGraphMemoryStore` is read-through over `PostgresIntelligenceMemoryRepository`; `upsert_node()` and `upsert_edge()` are no-op in this first version.
- Graph IDs use the existing object IDs directly. Topic/source/report synthetic nodes are allowed when query context needs them.
- Historical context composes Recall v2, TimelineService, and optional GraphMemoryService; empty or missing providers return deterministic empty context rather than raising.
- Consolidation services default to dry-run and emit proposed changes. Mutating behavior is limited to repository methods already available and only when `dry_run=False`.
- Existing `business/memory/feedback_memory.py` is extended, preserving `estimate_previous_misrank_penalty`.
- Worker handler supports injected services for tests and builds a Postgres service only when explicit memory Postgres env settings are present.

## Risks / Trade-offs

- Graph projection depth is limited by repository query methods rather than a graph database -> keep traversal deterministic and bounded.
- Evaluation metrics rely on repository list/search methods that may be approximate -> expose metadata and warnings with each report.
- Consolidation can identify proposed changes before all mutation methods exist -> default to dry-run and count skipped changes clearly.
