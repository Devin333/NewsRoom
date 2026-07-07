# Design

## Context

`rag-tenant-scope-guard` added tenant scope propagation and deterministic source verification. It also exposed tenant/user scope in gated service metrics to prove plumbing. That is useful internally, but public `PaperRagApplicationService.rag_ask()` payloads should not disclose user identifiers, memory namespace names, or allowed namespace lists.

## Goals / Non-Goals

**Goals:**
- Filter sensitive scope fields from retrieve-only and gated Paper RAG response metrics.
- Preserve low-risk operational fields such as `tenant_id`, trace ids, counts, status, decision type, budget snapshots, and filtered-passage counters.
- Keep `RAGSessionMetrics` and Harness state unchanged so internal diagnostics remain complete.
- Ensure nested metric payloads cannot leak namespace or user-scope fields.

**Non-Goals:**
- Add authentication or authorization middleware.
- Change tenant retrieval filters or `SourceVerifier` tenant scope semantics.
- Remove tenant/user fields from internal session specs, transcripts, or durable metrics.
- Redact answer text, passage text, or citations beyond tenant-scope metadata.

## Decisions

1. Sanitize only at the service payload boundary.
   - Rationale: the interface response is the external trust boundary; internal metrics and transcripts remain useful for debugging and audit.
   - Alternative: remove `user_id` and `memory_namespace` from `RAGSessionMetrics`. Rejected because that would weaken internal observability.

2. Use a recursive deny-list sanitizer for metrics.
   - Rationale: retrieval adapters and session metadata may add nested scope fields over time.
   - Alternative: hand-pick every allowed metric key. Rejected because existing metric payloads are broad and already used by callers.

3. Preserve `tenant_id`.
   - Rationale: callers often need to confirm the active tenant scope and it is less sensitive than user-specific or namespace-specific fields.
   - Alternative: remove all scope fields. Rejected because it makes tenant-scoped troubleshooting harder and loses the active request scope indicator.

## Risks / Trade-offs

- [Risk] A caller that depended on `metrics.user_id` or `metrics.memory_namespace` will lose those fields. -> Mitigation: those are internal scope fields; tenant id and trace ids remain available for support correlation.
- [Risk] A new sensitive key may be introduced under another name. -> Mitigation: sanitize exact scope keys and key fragments such as `memory_namespace`, `namespace`, and `user_id` recursively.
- [Risk] Over-filtering removes useful retrieval metadata. -> Mitigation: keep core counters and only filter scope/security identifiers.
