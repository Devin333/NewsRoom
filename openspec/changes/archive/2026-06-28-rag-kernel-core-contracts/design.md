## Context

The detailed PRD at `docs/superpowers/specs/2026-06-27-rag-kernel-decoupling-design.md` selects the "kernel + adapter" architecture: `framework/rag` owns reusable RAG contracts, `framework/harness/rag` owns bounded orchestration, and `business/research/rag` owns Paper RAG adaptation.

Current `business/research/rag` has real retrieval, benchmark, visual, and answer-evaluation code. It already converts `PaperChunk` into Harness `EvidencePack` in `business/research/rag/retrieval_port.py`, but that conversion is tightly coupled to paper metadata and cannot be reused by other domains. This change is the first migration slice: create neutral contracts and a Research-owned Paper adapter without changing ranking algorithms or benchmark behavior.

## Goals / Non-Goals

**Goals:**

- Introduce `framework/rag/core` with domain-neutral DTOs and ports.
- Make `framework/rag` importable without any `business.research` dependency.
- Add Paper adapter utilities under `business/research/rag/adapters`.
- Preserve existing Paper RAG retrieval behavior while giving later changes a stable contract to target.
- Add tests for DTO behavior, Paper adapter projection, and import boundaries.

**Non-Goals:**

- Do not move or rewrite `ResearchRetriever`.
- Do not change scoring, rerank, visual fusion, field embedding, or benchmark metrics.
- Do not move CLI entrypoints.
- Do not connect `framework/harness/rag` to the new kernel in this slice.
- Do not introduce new production fake data paths.

## Decisions

1. Add a small `framework/rag/core` package first.
   - Rationale: Later context, scoring, evaluation, and Harness integration need stable DTOs before behavior can move.
   - Alternative: Move scoring first. Rejected because it risks benchmark drift before contracts are explicit.

2. Use dataclasses for framework DTOs.
   - Rationale: The framework layer should stay lightweight, domain-neutral, and easy to serialize without importing business validation helpers.
   - Alternative: Use existing `PrimitiveModel`. Rejected because that would pull business-layer foundations into framework contracts.

3. Keep `PaperChunk` mapping inside `business/research/rag/adapters`.
   - Rationale: `PaperChunk`, formula metadata, figure ids, table ids, and source locator conventions are Research concerns.
   - Alternative: Put mapping helpers in `framework/rag`. Rejected because it would leak paper semantics into the reusable kernel.

4. Preserve raw locator strings while also parsing common page/bbox fields when possible.
   - Rationale: Current artifacts already carry source locators such as `paper://p1/pdf#page=6&pdf_rect=1,2,3,4`; adapters should not lose that string even if parsing only handles known keys.
   - Alternative: Require all locators to be fully structured immediately. Rejected because it would force a broad parser migration outside this slice.

5. Keep existing `PaperChunkRetrievalPort` behavior unchanged.
   - Rationale: This first change creates reusable contracts and tests without changing retrieval output ordering.
   - Alternative: Rewire `PaperChunkRetrievalPort` to emit the new DTOs immediately. Rejected because Harness currently consumes `EvidencePackCollection`, and V5 is the intended integration phase.

## Risks / Trade-offs

- [Risk] The first kernel slice looks small compared to the full PRD. → Mitigation: scope it explicitly to V0/V1 and create later OpenSpec changes for context/retrieval/evaluation.
- [Risk] DTO fields become too paper-shaped. → Mitigation: import-boundary and keyword tests reject Research imports and paper parser terms in `framework/rag`.
- [Risk] Adapter metadata copies too much. → Mitigation: expose core typed fields plus pass-through metadata; later slices can normalize scoring metadata gradually.
- [Risk] Existing benchmark behavior is not exercised by the new tests. → Mitigation: keep existing retrieval untouched and run existing Research RAG tests after adding adapter tests.

## Migration Plan

1. Add `framework/rag/core` DTOs and ports.
2. Add `business/research/rag/adapters/paper_chunk_adapter.py`.
3. Add framework core tests and Paper adapter tests.
4. Add import-boundary tests for `framework/rag`.
5. Validate the OpenSpec change and run compile plus targeted tests.

Rollback is straightforward: remove the new `framework/rag` package, Paper adapter package, tests, and this OpenSpec change. No existing runtime path should depend on the new contracts during this slice.

## Open Questions

- None for this slice. Harness integration, retrieval scoring extraction, and evaluation extraction are intentionally deferred to later PRD phases.
