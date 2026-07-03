# Design

## Scope Model

`AskPaperUseCase.build_paper_ask_goal()` accepts optional `tenant_id`, `user_id`, and `memory_namespace`.

Default namespaces:

- no tenant/user: `research.public`
- user only: `research:user:{user_id}`
- tenant only: `research:tenant:{tenant_id}:public`
- tenant and user: `research:tenant:{tenant_id}:user:{user_id}`

When a tenant or user is provided, a caller-supplied namespace must match that scope.

## Harness Guard

`ResearchRAGPolicyBuilder` copies tenant/user scope into `RAGSessionSpec.metadata`, `RetrievalGoal.metadata`, and `source_policy`.

`BoundedRAGSessionController` includes the scope in retrieval request filters and metadata. This is advisory for retrieval adapters.

`SourceVerifier` is authoritative: when `source_policy.tenant_id` is set, evidence that explicitly declares a different tenant is rejected with `rejection_reason="tenant_scope_violation"` and a `rag_tenant_scope` gate result.

Public/unscoped evidence remains allowed because many paper chunks are global public artifacts.

## Evidence Tenant Tags

The verifier checks tenant hints in evidence metadata and tenant URI refs:

- `tenant_id`, `tenant`, `workspace_id`
- `tenant_ids`, `allowed_tenant_ids`
- refs beginning with `tenant://{tenant_id}/...`
