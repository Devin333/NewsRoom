# Method

## Decision Criteria

Supported claims match supplied source text. Contradicted claims directly conflict with supplied source text. Unclear claims are unsupported, over-specific, over-broad, or only partially grounded.

## Step-by-Step Procedure

Map sources by id, evaluate each claim, collect evidence spans, assign status, write an explanation, add a suggested rewrite when needed, and compute summary counts.

## Scoring or Classification Rules

Use `supported` only for direct support. Use `unclear` for extrapolation or missing context. Use `contradicted` when sources state the opposite or incompatible facts.

## Edge Cases

If one source supports and another contradicts a claim, choose `contradicted` and include both source id arrays. If the claim contains multiple subclaims, mark it unclear unless all key subclaims are supported.
