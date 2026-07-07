## 1. Retrieval Filter Propagation

- [x] 1.1 Add filters to the Research retrieval request contract.
- [x] 1.2 Preserve Harness retrieval filters in the Paper RAG retrieval port adapter.
- [x] 1.3 Merge request filters with route filters before channel/store queries.

## 2. Business Tenant Policy

- [x] 2.1 Add Research-owned tenant visibility helpers for chunk metadata.
- [x] 2.2 Add Research-owned public metrics sanitization helpers.
- [x] 2.3 Replace interface-local tenant visibility and metrics sanitization logic with business service calls.

## 3. Tests

- [x] 3.1 Add retrieval port coverage for tenant filter propagation.
- [x] 3.2 Add Research retrieval coverage proving tenant and route filters reach chunk store queries.
- [x] 3.3 Update Paper RAG service tests for business-owned visibility and public metrics sanitization.
- [x] 3.4 Run targeted RAG, interface, architecture, compile, and OpenSpec validation checks.
