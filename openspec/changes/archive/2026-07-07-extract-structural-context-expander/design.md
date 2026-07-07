## Context

`ResearchRetriever` still interleaves structural context into child chunks before supplemental table hits and parent/ref expansion. This includes figure nearby/body refs, table nearby/body/parent refs, and formula refs from `FormulaContextExpander`.

## Goals / Non-Goals

**Goals:**

- Move structural interleaving into `StructuralContextExpander`.
- Preserve child ordering and per-source max context limits.
- Preserve expansion metadata and source locator inheritance.

**Non-Goals:**

- Do not move supplemental table child injection yet.
- Do not change formula/table/figure context rules.
- Do not build the final retrieval pipeline in this slice.

## Decisions

- **Expander returns chunks:** Unlike `FormulaContextExpander`, structural interleaving owns metadata application and returns the expanded child chunk list.
- **Formula expander is composed:** `StructuralContextExpander` uses `FormulaContextExpander` for formula refs rather than duplicating formula logic.
- **Table result predicate imported:** The expander uses `should_expand_result_context` from `table_context.py` to keep table result gating consistent.

## Risks / Trade-offs

- **Temporary helper duplication for metadata** -> The expansion metadata helper also exists in other expanders during migration; consolidation can happen after the expander set is complete.
