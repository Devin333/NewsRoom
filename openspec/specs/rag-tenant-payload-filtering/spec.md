# rag-tenant-payload-filtering Specification

## Purpose
TBD - created by archiving change rag-tenant-payload-filtering. Update Purpose after archive.
## Requirements
### Requirement: Paper RAG public metrics filter internal scope fields
Paper RAG service response metrics SHALL remove internal tenant-scope fields that identify users or memory namespaces while preserving safe operational counters.

#### Scenario: Retrieve-only metrics are sanitized
- **WHEN** `rag_ask(generate=False, tenant_id=..., user_id=...)` returns
- **THEN** response metrics include the active `tenant_id` and filtered-passage count when applicable
- **AND** response metrics do not include `user_id`, `memory_namespace`, allowed memory namespace lists, or nested namespace/user fields

#### Scenario: Gated metrics are sanitized
- **WHEN** `rag_ask(generate=True, tenant_id=..., user_id=...)` returns
- **THEN** response metrics include status, decision type, trace ids, tenant id, budget usage, evidence counts, answer counters, and gate counters
- **AND** response metrics do not include `user_id`, `memory_namespace`, allowed memory namespace lists, or nested namespace/user fields

### Requirement: Paper RAG keeps internal scope state
Paper RAG SHALL keep tenant/user scope in internal Harness goals, session specs, and `RAGSessionMetrics` even when public response metrics are sanitized.

#### Scenario: Internal goal still carries user scope
- **WHEN** a gated Paper RAG ask is invoked with tenant and user ids
- **THEN** the Harness goal still carries the tenant/user metadata and tenant-user memory namespace
- **AND** the public payload omits the user id and memory namespace
