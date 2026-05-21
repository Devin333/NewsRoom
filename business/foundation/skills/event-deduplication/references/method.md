# Method

## Decision Criteria

Two items are the same event when they share the same central entities, event action, timeframe, and factual claim.

## Step-by-Step Procedure

Normalize item ids, compare entity overlap, compare action verbs and event objects, check timing, group same-event items, select a canonical source, and emit duplicate pairs for important comparisons.

## Scoring or Classification Rules

Use high confidence above `0.85` for direct announcement plus coverage of the same release. Use low confidence below `0.6` when only topic overlap exists.

## Edge Cases

Same company plus same date is insufficient when products differ. A paper and implementation repository can be same event only when one is explicitly about the release of the other.
