## Context

Parent context expansion currently follows this shape:

1. Child chunks are ranked by vector score or reranker score plus position bias.
2. Parent candidates are derived through `parent_chunk_id`.
3. Parent candidates are deduplicated and optionally reranked.
4. Budgets and snippet rules decide how much parent context is returned.

The missing piece is an explicit score that explains parent ordering across child relevance, parent relevance, section heading relevance, and position.

## Goals

- Produce a deterministic `parent_final_score` for every parent candidate.
- Expose score components for debugging and downstream evidence inspection.
- Let parent reranker improve parent relevance without making reranker mandatory.
- Make section title and section role explicit scoring signals.
- Keep child rank as tie-break so ordering stays stable.

## Non-Goals

- Changing child retrieval scoring.
- Changing parser/chunker output.
- Adding a new reranker model.
- Changing table-specific deterministic edges.

## Scoring Formula

Parent context ranking should use:

```text
parent_final_score =
  child_relevance_score * child_weight
+ parent_relevance_score * parent_weight
+ section_heading_score * heading_weight
+ position_score * position_weight
```

Where:

- `child_relevance_score`: normalized score already attached to the matched child, preferring `fused_score`, then `text_score`.
- `parent_relevance_score`: parent reranker score when available; otherwise deterministic fallback derived from child relevance and heading relevance.
- `section_heading_score`: deterministic match between query intent and parent `section_title` / `section_role`.
- `position_score`: normalized version of existing position bias for the parent section.

## Intent-Specific Weights

Default weights:

```text
child=0.45, parent=0.35, heading=0.15, position=0.05
```

Intent overrides:

```text
concept_method: child=0.40, parent=0.30, heading=0.20, position=0.10
contribution: child=0.40, parent=0.30, heading=0.20, position=0.10
numerical_result: child=0.35, parent=0.40, heading=0.20, position=0.05
comparison: child=0.35, parent=0.40, heading=0.20, position=0.05
table_query: child=0.45, parent=0.25, heading=0.20, position=0.10
formula_query: child=0.45, parent=0.25, heading=0.20, position=0.10
```

Weights should be configurable through `RetrievalPolicy`.

## Metadata

Each returned parent context chunk should expose:

- `parent_child_relevance_score`
- `parent_relevance_score`
- `parent_section_heading_score`
- `parent_position_score`
- `parent_final_score`
- `parent_score_strategy`
- `parent_score_weights`

Retrieval metadata should expose:

- `parent_scoring_enabled`
- `parent_score_weights`
- `parent_candidates_scored`
- `parent_score_top`
- `parent_score_min`

## Fallbacks

- If reranker is unavailable, parent relevance is deterministic and scoring still works.
- If reranker fails or returns malformed output, the system falls back to deterministic scoring.
- If scores tie, sort by child rank and then parent chunk id for stable ordering.
