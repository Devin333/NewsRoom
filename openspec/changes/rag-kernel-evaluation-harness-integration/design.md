## Context

Research currently owns benchmark metrics such as Hit@K, MRR, source locator coverage, and answer success diagnostics. Those metrics are useful beyond Paper RAG, so this change adds generic metric calculators under `framework/rag/evaluation`. Harness RAG currently consumes `EvidenceCandidate`, while the new kernel produces `RAGEvidence`; this change adds a narrow adapter rather than rewiring the session controller.

## Goals / Non-Goals

**Goals:**

- Provide domain-neutral retrieval metrics: Hit@K, MRR, nDCG, evidence coverage, context recall, and source locator coverage.
- Provide lightweight answer metrics: fact coverage, citation grounding, answer relevance, faithfulness proxy, and abstention accuracy.
- Provide generic failure reason constants and scorecard/report serialization.
- Add Harness conversion from `RAGEvidence` to `EvidenceCandidate`.

**Non-Goals:**

- Do not replace Research benchmark suite in this slice.
- Do not add LLM judge calls or model-based faithfulness scoring.
- Do not change `BoundedRAGSessionController` execution behavior.
- Do not archive or remove Research evaluation modules yet.

## Decisions

1. Keep metrics deterministic.
   - Rationale: The project needs cheap regression checks before optional LLM judge layers.
   - Alternative: Start with model-based evaluators. Rejected because it would add network/model dependencies and unstable tests.

2. Model metric results as serializable dataclasses.
   - Rationale: Both CLI reports and quality gates need structured values with explanations.
   - Alternative: Return raw floats only. Rejected because failure analysis needs metric names and metadata.

3. Put Harness bridge in `framework/harness/rag`.
   - Rationale: Harness already owns `EvidenceCandidate`, so conversion from kernel evidence into Harness evidence is a Harness concern.
   - Alternative: Put conversion inside `framework/rag`. Rejected because that would make the generic kernel depend on Harness model shape.

## Risks / Trade-offs

- [Risk] Deterministic answer metrics are only proxies for true answer quality. → Mitigation: expose metric metadata and leave LLM judge integration for a later phase.
- [Risk] Research benchmark still uses its current calculators. → Mitigation: keep this additive first; later migration can swap calculators behind existing reports.
- [Risk] Harness adapter duplicates some evidence-pack mapping behavior. → Mitigation: keep the adapter narrow and covered by tests.

## Migration Plan

1. Add evaluation models and calculators.
2. Add report/failure reason helpers.
3. Add Harness evidence adapter.
4. Add focused tests and run existing Research/Harness RAG tests.

Rollback removes only the new evaluation package, Harness adapter, tests, and this OpenSpec change.

## Open Questions

- None for this slice. Research benchmark migration and model-judge scoring remain later work.
