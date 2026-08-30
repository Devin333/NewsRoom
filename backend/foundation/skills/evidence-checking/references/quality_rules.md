# Quality Rules

## Required Checks

Validate schema, ensure claim ids match input, ensure source ids exist, verify evidence spans come from source text, and recompute summary counts.

## Common Failure Modes

Common failures include using citations that were not supplied, treating a source title as full support, and omitting rewrites for unclear claims.

## Safe Defaults

When evidence is partial, mark the claim `unclear` and suggest a narrower rewrite.

## Output Validation Rules

Each claim result must include all required fields, arrays must be present even when empty, and summary counts must equal the statuses returned.
