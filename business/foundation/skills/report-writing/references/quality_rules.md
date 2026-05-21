# Quality Rules

## Required Checks

Validate schema, ensure Markdown is non-empty, ensure each section has item ids, ensure citations reference supplied items, and ensure unclear evidence appears in warnings.

## Common Failure Modes

Common failures include writing broad claims without citations, omitting source names, and hiding uncertainty from unclear evidence.

## Safe Defaults

When evidence is unclear, include a warning and use tentative wording.

## Output Validation Rules

The output must contain all required fields, citation objects must have item id, URL, and source name, and warnings must be an array even when empty.
