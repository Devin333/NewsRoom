## Context

Paper RAG currently has semantic retrieval, field embedding retrieval, deterministic field scoring, sparse lexical recall, RRF fusion, visual retrieval, claim retrieval, reranking hooks, parent expansion, and table/result graph expansion. The latest real blind semantic run shows that this stack works well for figure, citation, and table questions, but formula slices remain weak:

- `formula_qa Hit@10 = 0.667`, `MRR = 0.444`
- `formula_explanation_qa Hit@10 = 0.667`, `MRR = 0.405`, `evidence coverage@10 = 0.600`

The existing field extraction path already supports formula-facing fields such as `formula_latex`, `formula_description`, `metadata.formula_normalized_latex`, `metadata.formula_symbols`, `metadata.formula_operators`, and `metadata.formula_referenced_text`. The design should strengthen those fields and retrieval paths without introducing mandatory network/model dependencies.

## Goals / Non-Goals

**Goals:**
- Normalize formula LaTeX into stable retrieval metadata.
- Add formula-specific sparse scoring over symbols, operators, structure tokens, labels, and explanation context.
- Add a policy-gated formula retrieval profile that improves formula ranking while preserving default behavior.
- Strengthen formula-to-explanation graph expansion with explicit edge metadata and source locator preservation.
- Add formula-specific failure diagnostics and benchmark summaries.
- Extend gold/judge quality reporting so blind semantic formula gold can be audited and repaired.

**Non-Goals:**
- Do not train or require a new formula embedding model.
- Do not add a mandatory MathML or CAS dependency.
- Do not replace existing semantic, field embedding, or RRF retrieval.
- Do not change PDF parsing or Nougat/Surya extraction in this change.
- Do not treat LLM gold judge output as final truth without human calibration support.

## Decisions

1. **Use deterministic formula normalization first.**
   - Decision: add a local normalizer that extracts normalized LaTeX, symbols, operators, structure tokens, reference labels, and context terms.
   - Rationale: formula retrieval failures are often exact-symbol or exact-label misses; deterministic metadata is cheap, testable, and visible in score breakdowns.
   - Alternative considered: introduce a formula embedding model immediately. Deferred because it adds runtime/model complexity before deterministic gains are measured.

2. **Keep formula retrieval behind a named policy.**
   - Decision: add `paper_formula_rag_v1` as an explicit policy that builds on `paper_hybrid_rrf_rag_v1`.
   - Rationale: default behavior and prior benchmark policies remain stable, while the new policy can be A/B tested on dev/test splits.
   - Alternative considered: retune `paper_hybrid_rrf_rag_v1` in place. Rejected because it would blur regression attribution.

3. **Implement formula sparse scoring as a score component, not a separate store.**
   - Decision: calculate formula sparse scores from existing `PaperChunk` fields during retrieval, then preserve the breakdown in metadata.
   - Rationale: this avoids schema/store migrations and keeps the first slice offline-testable.
   - Alternative considered: build a persistent formula inverted index. Deferred until real benchmark runs prove the in-memory score path is a bottleneck.

4. **Treat formula explanations as graph expansion edges.**
   - Decision: use `formula_referenced_text`, `referenced_by_chunks`, explicit equation references, parent context, and nearby explanation heuristics to expand formula evidence.
   - Rationale: `formula_explanation_qa` requires both formula evidence and explanatory paragraph evidence; graph expansion is the right abstraction because it is capped, observable, and source-locator-aware.
   - Alternative considered: always append nearby paragraphs for formula queries. Rejected because it would increase noise and hurt `@3/@5`.

5. **Make gold quality warnings actionable.**
   - Decision: emit gold failure manifests and judge summaries that distinguish ambiguous questions, bad gold, missing context, and retrieval failures.
   - Rationale: retrieval scores should not be optimized against bad or underspecified gold evidence.
   - Alternative considered: ignore `gold_audit_warning` while optimizing retrieval. Rejected because it can cause overfitting to benchmark artifacts.

## Risks / Trade-offs

- Formula normalization can over-tokenize LaTeX commands -> keep raw, normalized, and component fields side by side for debugging.
- Sparse scoring can over-boost coincidental symbol matches -> combine symbols with operators/context/labels and expose score components.
- Graph expansion can add noisy context -> cap formula context chunks and require explicit `expansion_reason`/`graph_score` metadata.
- In-memory formula scoring can add retrieval latency -> only enable it for formula policies/intents and keep candidate limits bounded.
- LLM judge can be inconsistent -> treat human labels as final calibration and keep deterministic audit as the base gate.

## Migration Plan

1. Add formula normalization helper and unit tests.
2. Route formula field extraction through the normalizer without changing persisted chunk shape requirements.
3. Add formula sparse score components and `paper_formula_rag_v1`.
4. Strengthen formula graph expansion and source locator inheritance.
5. Add formula diagnostics and gold failure manifest support.
6. Run targeted tests, OpenSpec validation, compile checks, and a real benchmark comparison if local data is available.
7. Keep rollback simple: use the prior `paper_hybrid_rrf_rag_v1` policy.
