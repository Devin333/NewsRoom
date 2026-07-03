## Context

`HybridSearchService` was introduced for an older storage/memory target closure as a report keyword plus vector-result merge baseline. PRD 16's enterprise review found it is not a real hybrid retrieval implementation and has no production callers. The actual paper retrieval path now uses explicit retrieval channels and fusion inside `business.research.rag.retrieval`.

## Goals / Non-Goals

**Goals:**

- Remove the orphan storage-layer hybrid search implementation and tests.
- Update active OpenSpec requirements so they do not keep asking for the deleted orphan service.
- Preserve all real Paper RAG retrieval behavior.

**Non-Goals:**

- Do not modify Paper RAG sparse/BM25 retrieval.
- Do not introduce a replacement storage search service.
- Do not touch archived specs.

## Decisions

- **Delete rather than deprecate:** There are no production callers, so keeping a shim only preserves confusion.
- **Spec deletion is required:** The active storage spec currently requires the service, so code deletion must be paired with a requirement removal.
- **Archived specs stay immutable:** Historical archived changes still mention the old capability, but active specs and code define the current target.

## Risks / Trade-offs

- **Future callers cannot use the old service:** This is intentional. They should use the explicit retrieval pipeline or introduce a new spec-backed storage search capability.
