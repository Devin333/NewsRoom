## 1. Scope Propagation

- [x] 1.1 Add paper ask tenant/user scope normalization.
- [x] 1.2 Propagate tenant/user scope into RAG session spec policy and metadata.
- [x] 1.3 Include tenant/user scope in retrieval request metadata and filters.

## 2. Deterministic Guard

- [x] 2.1 Reject explicitly cross-tenant evidence in `SourceVerifier`.
- [x] 2.2 Emit `rag_tenant_scope` gate results and rejection metadata.

## 3. Interface Exposure

- [x] 3.1 Add paper RAG service parameters for tenant/user scope.
- [x] 3.2 Include tenant/user scope in gated response metrics.
- [x] 3.3 Add CLI options for tenant/user scope.

## 4. Tests And Validation

- [x] 4.1 Add unit tests for tenant goal normalization and namespace rejection.
- [x] 4.2 Add source verifier and session propagation tests.
- [x] 4.3 Add service/CLI tests for tenant scope plumbing.
- [x] 4.4 Run targeted tests, compile, smoke, and strict OpenSpec validation.
