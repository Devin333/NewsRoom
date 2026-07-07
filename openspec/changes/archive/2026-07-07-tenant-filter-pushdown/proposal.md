## Why

Tenant-scoped Paper RAG asks already place `tenant_id` on the Harness retrieval request, but that filter is lost when the request is converted into the Research retrieval request. This leaves tenant isolation relying on later verifier and interface filtering instead of pushing the scope into the retrieval/store query itself.

## What Changes

- Preserve request filters when `PaperKernelRAGRetriever` converts Harness retrieval requests into Research retrieval requests.
- Apply tenant filters through the Research retrieval planner and channel/store query path so cross-tenant chunks are filtered before evidence is packed.
- Move tenant visibility and public metrics sanitization rules out of `interfaces/services/paper_rag_service.py` into a Research-owned business service.
- Keep public/unscoped paper chunks visible to tenant-scoped asks while rejecting chunks explicitly scoped to another tenant.
- Add targeted tests for filter propagation, retrieval filtering, interface payload behavior, and architecture boundaries.

## Capabilities

### New Capabilities
- `rag-tenant-filter-pushdown`: tenant-aware Paper RAG retrieval filtering and Research-owned public payload visibility rules.

### Modified Capabilities

## Impact

- Affected code: `business/research/rag/retrieval`, `business/research/rag/retrieval_port.py`, `business/research/services`, and `interfaces/services/paper_rag_service.py`.
- Affected tests: Paper RAG retrieval, retrieval port, Paper RAG service tenant payload tests, and architecture boundary checks.
- No API schema, persistence migration, authentication, or dependency changes are expected.
