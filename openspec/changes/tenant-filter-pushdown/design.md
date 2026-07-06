## Context

`rag-tenant-scope-guard` already propagates tenant/user scope into Harness session metadata and retrieval request filters, and `SourceVerifier` rejects explicitly cross-tenant evidence. The current gap is the Research adapter boundary: `PaperKernelRAGRetriever` converts a Harness `RetrievalRequest` into a Research `ResearchRetrievalRequest` that does not carry `filters`, so storage-backed retrieval cannot apply tenant filtering before evidence candidates are built.

The interface service also owns tenant visibility and metrics sanitization helpers. Those rules are business policy, and they are needed by both retrieve-only response filtering and public response payload construction.

## Goals / Non-Goals

**Goals:**
- Preserve Harness retrieval filters when entering Research Paper retrieval.
- Merge request filters with route-specific retrieval filters before channel/store queries run.
- Apply tenant visibility consistently in business-owned code.
- Reuse business-owned public metrics sanitization from the interface service response boundary.
- Keep public/unscoped chunks visible to tenant-scoped asks.

**Non-Goals:**
- Changing tenant namespace construction, authentication, authorization middleware, or `SourceVerifier` tenant-scope semantics.
- Redacting answer text, passage text, citations, or transcript internals.
- Adding persistence migrations or changing external API schemas.

## Decisions

1. Add `filters: dict[str, Any]` to the Research retrieval request contract.
   - Rationale: request filters are part of retrieval intent and must survive the Harness-to-Research adapter boundary.
   - Alternative: keep filters only in Harness metadata. Rejected because retrieval channels and chunk stores already accept filter arguments and should not need to parse opaque metadata.

2. Merge request filters before route extra filters in the retrieval planner.
   - Rationale: caller scope filters such as `tenant_id` should apply to every route, while route extras such as `chunk_type` narrow a specific channel.
   - Alternative: pass both maps separately to each channel. Rejected because it duplicates merge policy in channel implementations.

3. Put tenant visibility and public metrics sanitization in `business/research/services/tenant_visibility.py`.
   - Rationale: tenant visibility and scope-field redaction are Research business rules. The interface layer should apply the final business rule at the response boundary, not define the rule.
   - Alternative: leave helpers private in `paper_rag_service.py`. Rejected because retrieve-only filtering, gated metrics, and future Research services would continue to duplicate policy.

4. Filter explicitly cross-tenant chunks while allowing public chunks.
   - Rationale: many paper artifacts are global public chunks. Tenant-scoped asks should hide chunks tagged for another tenant without losing untagged public evidence.
   - Alternative: require every visible chunk to carry the active tenant id. Rejected because it would break existing public paper corpora and over-filter shared research artifacts.

## Risks / Trade-offs

- [Risk] A retrieval adapter may use non-storage internal filter keys. -> Mitigation: copy only the request filter map as received and keep route-specific filtering in existing planner/channel contracts; add tests around the known `tenant_id` key.
- [Risk] Filter merge order could accidentally drop route filters. -> Mitigation: tests assert both caller tenant filters and route chunk-type filters reach store calls.
- [Risk] Metrics sanitization might over-filter useful diagnostics. -> Mitigation: preserve `tenant_id`, trace ids, status, counters, budget snapshots, and other operational fields while recursively removing user and namespace scope identifiers.
