# rag-tenant-filter-pushdown Specification

## Purpose
TBD - created by archiving change tenant-filter-pushdown. Update Purpose after archive.
## Requirements
### Requirement: Paper RAG retrieval preserves tenant filters
Paper RAG retrieval SHALL preserve tenant filters from Harness retrieval requests when converting into Research retrieval requests and SHALL pass those filters to chunk store queries.

#### Scenario: Tenant filter reaches Research retrieval
- **WHEN** a Harness retrieval request includes `filters.tenant_id`
- **THEN** the Paper RAG retrieval port passes `tenant_id` into the Research retrieval request

#### Scenario: Tenant filter reaches chunk store query
- **WHEN** Research retrieval plans channel queries for a tenant-scoped request
- **THEN** each chunk store query receives the tenant filter together with route-specific filters

### Requirement: Tenant visibility is enforced before public payload construction
Paper RAG public response construction SHALL use Research-owned tenant visibility rules to hide chunks explicitly scoped to another tenant while keeping public chunks visible.

#### Scenario: Cross-tenant retrieved passage is hidden
- **WHEN** a retrieve-only Paper RAG response is built for `tenant-a`
- **AND** retrieved chunks include one public chunk and one chunk tagged for `tenant-b`
- **THEN** the response includes the public chunk
- **AND** the response excludes the `tenant-b` chunk
- **AND** response metrics record the filtered passage count

### Requirement: Public Paper RAG metrics are sanitized by Research policy
Paper RAG public response metrics SHALL use Research-owned sanitization rules that preserve safe operational fields and remove user or namespace scope identifiers recursively.

#### Scenario: Gated metrics are sanitized at the response boundary
- **WHEN** a gated Paper RAG response includes internal user or namespace scope fields in metrics
- **THEN** public response metrics preserve safe operational counters and `tenant_id`
- **AND** public response metrics do not include `user_id`, memory namespace fields, allowed namespace lists, or nested user/namespace fields
