# RAG Tenant Scope Guard

## Why

The enterprise RAG review still scores multi-tenant/security as absent. Paper RAG has source and memory scope fields, but gated ask calls default to public memory and the source verifier does not reject evidence tagged for another tenant.

## What Changes

- Add tenant/user scope normalization for paper ask goals.
- Propagate tenant/user scope into RAG session specs and retrieval request metadata.
- Add deterministic source verification that rejects evidence explicitly tagged for a different tenant.
- Expose tenant/user scope in gated paper RAG response metrics.

## Out Of Scope

- HTTP authentication middleware.
- Tenant-specific database row-level security.
- Full dashboard or audit-log persistence.
