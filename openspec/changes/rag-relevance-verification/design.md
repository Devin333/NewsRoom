## Context

The bounded RAG controller already separates planning, execution, verification, and context assembly. Source verification is the right point to reject evidence that is structurally valid but unrelated to the user's question. This must stay framework-owned and deterministic: framework defines a scoring port and gate, while business code can later provide a concrete model-backed scorer.

## Goals / Non-Goals

**Goals:**
- Add a domain-neutral relevance scorer port.
- Add a deterministic threshold gate that reports low-scoring evidence ids.
- Reject low-relevance candidates in `SourceVerifier` only when a scorer and question are provided.
- Preserve exact acceptance behavior when `relevance_scorer=None`.
- Add rejected evidence reason metadata and summarize rejection reasons in the gap report.

**Non-Goals:**
- Wire a production CrossEncoder/reranker scorer.
- Tune thresholds against a benchmark.
- Change the planner or generation phase.
- Use an LLM judge for relevance verification.

## Decisions

1. Use a scorer port plus pure gate.

   `RelevanceScorerPort.score(question, passages)` returns floats in `[0, 1]`. `RAGRelevanceGate` only compares scores with a threshold and returns a `RAGGateResult`; it does not call models or perform free-form judgment.

2. Score against `spec.goal.question`.

   The verifier receives the original goal question from the session controller. Retrieval queries may be rewritten or gap-expanded in later tasks, but relevance verification must judge evidence against the user's actual question.

3. Store rejection reason on rejected candidate metadata.

   `EvidenceCandidate` is frozen, so `SourceVerifier` returns a copied candidate with metadata fields such as `rejection_reason`, `relevance_score`, and `relevance_threshold`. This keeps rejected evidence traceable without mutating accepted candidates.

4. Keep no-scorer compatibility.

   If no scorer is configured or no question is provided, `SourceVerifier` behaves like the current implementation. This makes the T2 framework foundation safe before production business wiring.

## Risks / Trade-offs

- Bad thresholds can reject useful short evidence such as formulas or tables. This slice makes the threshold configurable through `source_policy["min_relevance"]`; type-specific tuning can follow after benchmark calibration.
- A scorer implementation may fail or return a wrong number of scores. The framework verifier treats this as a relevance gate failure and rejects rather than silently accepting ambiguous evidence.
- `rejection_summary` adds more metadata to gap reports. It is small and deterministic, and later planner wiring can consume it directly.
