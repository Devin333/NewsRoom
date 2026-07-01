## Context

The current Paper RAG path already has semantic retrieval, field embedding, visual fusion, claim search, field scoring, parent expansion, table/result expansion, and benchmark reporting. Recent real benchmark runs show stable `Hit@10` around 0.78-0.81, `equivalent Hit@10` around 0.80-0.85, `MRR` around 0.55-0.65, and `evidence coverage@10` around 0.75-0.80. That is strong enough for internal evaluation, but enterprise usage needs better top-rank evidence and fuller multi-evidence context.

The implementation must keep default retrieval behavior compatible and introduce the stronger behavior through named retrieval policies. The first production-shaped slice should avoid mandatory network/model dependencies; neural rerankers remain pluggable through the existing reranker ports.

## Goals / Non-Goals

**Goals:**
- Promote `@3` and `@5` retrieval metrics into JSON, markdown, and promotion diagnostics.
- Add a Paper-specific hybrid policy that uses deterministic sparse lexical recall, multi-query variants, and RRF fusion on top of existing dense/field/visual/claim paths.
- Improve top-rank ordering by making sparse, field, graph, visual, and rerank score components explicit in child metadata.
- Improve multi-evidence coverage by expanding table, figure, formula, and result evidence through nearby and referenced context.
- Preserve source locator metadata on expanded, supplemental, parent, and snippet chunks.

**Non-Goals:**
- Do not replace the default retrieval policy.
- Do not introduce a required external reranker model in this change.
- Do not change PDF parsing or visual description generation.
- Do not remove existing strict/equivalent hit gap checks.

## Decisions

1. **Use a new named policy for stronger retrieval.**
   - Decision: add a policy such as `paper_hybrid_rrf_rag_v1`.
   - Rationale: current benchmark policies are useful baselines; a new policy gives A/B safety and rollback.
   - Alternative considered: change `paper_blind_semantic_rag_v1` directly. Rejected because it would make regression attribution harder.

2. **Implement deterministic sparse lexical retrieval before adding SPLADE.**
   - Decision: use local token scoring over the existing chunk store as the first sparse channel.
   - Rationale: it is testable, cheap, offline, and improves exact term/formula/table-column matching without model setup.
   - Alternative considered: add SPLADE immediately. Deferred because it adds model/runtime complexity and is better evaluated after deterministic gains are measured.

3. **Fuse recall channels with Reciprocal Rank Fusion.**
   - Decision: collect ranked lists from semantic, field, sparse, claim, and visual channels, then merge by chunk id using RRF-style score contributions.
   - Rationale: RRF is robust when score scales differ across retrieval methods.
   - Alternative considered: normalize raw scores directly. Rejected for the first slice because dense, lexical, field, and visual scores are not calibrated.

4. **Treat evidence expansion as a graph boost, not unbounded context injection.**
   - Decision: expanded chunks receive explicit `expansion_edge`, `expanded_from_chunk_id`, `graph_score`, and source locator preservation metadata, then continue through dedupe/ranking/context assembly.
   - Rationale: this improves evidence coverage while preserving diagnosability and noise control.
   - Alternative considered: always append all nearby chunks. Rejected because it would inflate noise and weaken `@3/@5`.

5. **Keep metrics broad but gates staged.**
   - Decision: report `@1/@3/@5/@10` everywhere, but start gates at pragmatic thresholds and tune against real blind datasets.
   - Rationale: top-k distribution matters more than a single `@10` score, but gates must not block unrelated development before enough runs exist.

## Risks / Trade-offs

- Sparse and multi-query recall can increase latency -> keep it policy-gated and limit candidate counts by intent.
- RRF may lift lexical false positives -> expose channel score breakdown and rely on rerank/field score to correct top ranks.
- Evidence graph expansion can add noise -> cap expansion counts and require expansion metadata for diagnostics.
- Source locator inheritance can be misleading if not marked -> add `source_locator_inherited` and `source_locator_origin_chunk_id` when inheriting from anchor chunks.
- `equivalent Hit@10` can hide strict regressions -> keep strict/equivalent gap reporting and promotion checks.

## Migration Plan

1. Add OpenSpec requirements and tests for the new policy/report behavior.
2. Implement report/gate additions for `@3/@5`.
3. Add deterministic sparse lexical recall and RRF fusion behind `paper_hybrid_rrf_rag_v1`.
4. Add graph expansion/source locator preservation helpers.
5. Run targeted tests, compile, OpenSpec validation, then real benchmark smoke if local data is available.
