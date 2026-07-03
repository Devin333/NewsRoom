## Context

The retrieval pipeline has already been split into planner, recall, ranking, expanders, and metrics stages. The remaining oversized `paper_retriever.py` mostly comes from contract and policy definitions that are used across retrieval, evaluation, answer generation, and tests. Keeping those definitions in the entrypoint makes `ResearchRetriever` look heavier than it is and blocks PRD 16's thin-entrypoint acceptance criterion.

## Goals / Non-Goals

**Goals:**

- Give retrieval DTOs a dedicated `contracts.py` owner.
- Give policy configuration objects and named-policy builders a dedicated `policies.py` owner.
- Preserve old imports from `paper_retriever.py` during this slice.
- Reduce `paper_retriever.py` toward a wiring-only module without changing runtime behavior.

**Non-Goals:**

- Do not migrate policy values to YAML in this slice.
- Do not rename public classes or fields.
- Do not change `RetrievalResult.as_evidence_candidates()` output.
- Do not update every test import unless needed; compatibility re-exports are intentionally preserved.

## Decisions

- **Compatibility first:** `paper_retriever.py` will import and re-export the moved symbols so existing callers keep working.
- **Policy module owns helper dependencies:** `policies.py` imports the scoring normalizers and field constants because policy methods directly depend on them.
- **Contracts module owns evidence conversion:** `RetrievalResult.as_evidence_candidates()` moves with the result DTO because it is part of the public result contract, not retriever wiring.
- **Dedicated dedupe helper stays private to contracts:** The result conversion keeps its local `_dedupe_chunks` helper to avoid introducing a broader abstraction for one call site.

## Risks / Trade-offs

- **Some callers may still import through `paper_retriever.py`:** This is acceptable during the compatibility phase. Later cleanup can move imports to the new modules once the entrypoint is stable.
- **`policies.py` remains large:** This slice changes ownership, not policy externalization. YAML-backed policy loading can happen under the existing policy-config PRD track.
