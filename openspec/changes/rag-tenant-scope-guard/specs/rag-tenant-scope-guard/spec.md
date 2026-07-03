## ADDED Requirements

### Requirement: Paper RAG asks carry tenant scope
Paper RAG ask flows SHALL support explicit tenant and user scope without defaulting scoped requests to public memory.

#### Scenario: Tenant scoped goal is built
- **WHEN** a paper ask goal is built with a tenant id and user id
- **THEN** the goal SHALL include tenant/user metadata and use the tenant user memory namespace

#### Scenario: Cross-scope namespace is rejected
- **WHEN** a tenant scoped paper ask goal is built with a namespace for another tenant
- **THEN** goal construction SHALL fail before any retrieval runs

### Requirement: RAG source verification enforces tenant scope
The source verifier SHALL reject evidence explicitly tagged for a tenant outside the active RAG source policy tenant.

#### Scenario: Cross-tenant evidence is retrieved
- **WHEN** a RAG source policy declares tenant `tenant-a`
- **AND** retrieved evidence declares tenant `tenant-b`
- **THEN** source verification SHALL reject that evidence with `tenant_scope_violation`
- **AND** emit a failed `rag_tenant_scope` gate result

#### Scenario: Public evidence is retrieved
- **WHEN** a RAG source policy declares a tenant
- **AND** retrieved evidence has no explicit tenant tag
- **THEN** source verification SHALL allow normal source quality, lineage, and relevance gates to decide the result

### Requirement: Tenant scope reaches gated paper RAG responses
Gated paper RAG service responses SHALL include tenant and user scope in metrics when supplied.

#### Scenario: Gated ask includes tenant metrics
- **WHEN** `rag_ask(generate=True, tenant_id=..., user_id=...)` returns
- **THEN** response metrics SHALL include the tenant id, user id, and allowed memory namespace

### Requirement: Tenant scoped retrieve-only payloads are filtered
Paper RAG retrieve-only responses SHALL NOT include passages explicitly tagged for another tenant.

#### Scenario: Cross-tenant passage is retrieved before payload construction
- **WHEN** `rag_ask(generate=False, tenant_id="tenant-a")` retrieves one public passage and one passage tagged `tenant-b`
- **THEN** the response SHALL include only the public passage
- **AND** metrics SHALL record the filtered passage count
