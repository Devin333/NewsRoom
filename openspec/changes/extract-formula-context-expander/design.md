## Context

Formula context expansion happens in two places: child/ref expansion and structural interleaving. Cross-reference expansion already owns formula reverse references for `ref_chunks`; this slice targets the structural interleaving path that adds formula context into child chunks.

## Goals / Non-Goals

**Goals:**

- Move formula context reference extraction into `FormulaContextExpander`.
- Preserve formula query gating and `max_formula_context_chunks` behavior.
- Keep expansion metadata application in `ResearchRetriever._interleave_structural_context` for now.

**Non-Goals:**

- Do not move all structural interleaving logic in this slice.
- Do not change formula sparse scoring or formula recall.
- Do not change cross-ref formula expansion already handled by `CrossRefContextExpander`.

## Decisions

- **References only:** The formula expander returns reference tuples, not chunks, because `_interleave_structural_context` still owns shared dedupe and metadata application for figure/table/formula child interleaving.
- **Policy-aware constructor:** The expander receives `RetrievalPolicy` so it can enforce `max_formula_context_chunks` and formula sparse behavior.
- **Question gating stays deterministic:** The same token rules for surrounding/explained/explain/meaning are preserved.

## Risks / Trade-offs

- **Partial expander contract** -> This expander currently returns refs rather than chunks; the final structural interleave expander can normalize this later.
- **Temporary duplicate formula helpers** -> Cross-ref and formula structural paths both have formula helper code until shared helper extraction.
