## Context

`framework/rag/core` now provides neutral DTOs, while existing Research RAG code still owns score fusion, field score metadata, parent/child expansion signals, overlap span citation metadata, and context budget behavior. This change adds generic primitives that later Research migration steps can call without changing runtime behavior in this slice.

## Goals / Non-Goals

**Goals:**

- Provide deterministic score fusion for `RAGScoreBreakdown`.
- Provide lexical field scoring that can explain which field matched a query.
- Provide evidence deduplication and sorted ordering helpers.
- Provide context budget trimming that preserves complete evidence objects and source locators.
- Provide citation resolution for `main_span` and `overlap_spans` metadata in a domain-neutral location.

**Non-Goals:**

- Do not migrate `ResearchRetriever` to these helpers yet.
- Do not add embeddings, reranker model calls, visual index changes, or benchmark data changes.
- Do not add table/result/conclusion expansion or formula reference graph traversal in this slice.
- Do not connect these helpers to `framework/harness/rag` yet.

## Decisions

1. Keep retrieval utilities as pure functions plus small dataclasses.
   - Rationale: The first migration target is testable, deterministic behavior that can be reused by Research without lifecycle concerns.
   - Alternative: Add a stateful retriever service. Rejected because the PRD defers retriever rewiring to a later phase.

2. Treat missing score components as absent.
   - Rationale: Current score metadata is sparse and differs by retrieval path; generic scoring must not fabricate components.
   - Alternative: Fill missing components with zero in the breakdown. Rejected because it hides observability gaps.

3. Deduplicate by chunk id by default and keep the highest scoring evidence.
   - Rationale: Retrieval results often expand parent/child/context candidates, and duplicate chunk ids should not inflate context.
   - Alternative: Keep first occurrence only. Rejected because later rerank stages may produce a better-scored duplicate.

4. Resolve citations from span metadata without parsing documents.
   - Rationale: Overlap provenance already travels through metadata; generic citation helpers can use it without knowing Paper chunks.
   - Alternative: Put citation resolution only in Research document code. Rejected because later non-Paper chunkers can use the same span contract.

## Risks / Trade-offs

- [Risk] Pure helpers are not yet used by production Research retrieval. → Mitigation: this is intentional for a behavior-preserving migration slice; later changes will wire them in behind tests.
- [Risk] Lexical scoring is weaker than embedding/reranker scoring. → Mitigation: use it only as deterministic field-score support and explanation, not as a replacement for vector retrieval.
- [Risk] Budget trimming can drop useful evidence. → Mitigation: trimming is score-ordered and never mutates evidence/source locator data.

## Migration Plan

1. Add retrieval scoring, field scoring, and dedup modules.
2. Add context budget, citation, and assembler modules.
3. Add focused tests for each primitive.
4. Validate OpenSpec and run framework/Research targeted tests.

Rollback removes only the new modules, tests, and OpenSpec change because no existing runtime path is rewired in this slice.

## Open Questions

- None for this slice. Research-specific expansion policies and Harness integration remain in later PRD phases.
