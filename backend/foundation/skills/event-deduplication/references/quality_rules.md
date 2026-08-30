# Quality Rules

## Required Checks

Validate schemas, ensure canonical ids are in their groups, ensure item ids exist in the input, and verify confidence values are bounded.

## Common Failure Modes

Common failures include merging by company alone, splitting official and secondary coverage of the same event, and choosing a weak community post as canonical when a primary source exists.

## Safe Defaults

When uncertain, create separate groups and record low-confidence duplicate pairs rather than over-merging.

## Output Validation Rules

Every event group must include an event id, one or more item ids, a canonical item id, and a confidence value between `0` and `1`.
