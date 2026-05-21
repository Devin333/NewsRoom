# Quality Rules

## Required Checks

Validate schema, verify every evidence span appears in input text, ensure each type is allowed, and remove exact duplicate entities.

## Common Failure Modes

Common failures include extracting generic nouns, losing repository casing, and treating vague phrases like "the company" as named entities.

## Safe Defaults

When uncertain, keep the entity but lower confidence and add a warning that normalization may need review.

## Output Validation Rules

Entity names and evidence spans must be non-empty, confidence must be between `0` and `1`, and warnings must be strings.
