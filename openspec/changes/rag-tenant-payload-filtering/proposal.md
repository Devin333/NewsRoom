# RAG Tenant Payload Filtering

## Why

The existing tenant scope guard prevents explicitly cross-tenant evidence from being accepted, but Paper RAG service responses still expose internal scope details such as `user_id` and `memory_namespace` in public payload metrics. The enterprise RAG review calls out tenant payload filtering as a remaining security gap after scope enforcement.

## What Changes

- Add a Paper RAG response sanitizer for public service payloads.
- Preserve `tenant_id`, trace ids, counts, and operational counters needed for callers.
- Remove internal scope fields such as `user_id`, `memory_namespace`, and allowed namespace lists from retrieve-only and gated response metrics.
- Keep internal `RAGSessionMetrics`, session specs, retrieval filters, and source verification unchanged.
- Add tests proving public payloads are scoped and sanitized while session scope still reaches Harness.

## Capabilities

### New Capabilities
- `rag-tenant-payload-filtering`: safe tenant-aware public payload filtering for Paper RAG service responses.

### Modified Capabilities

## Impact

Affected code is limited to `interfaces/services/paper_rag_service.py` and service tests. No persistence migration, authentication middleware, or retrieval policy change is required.
