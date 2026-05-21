# Quality Rules

## Required Checks

Check schema validity, score range, supported tier values, allowed risk flags, and evidence observations tied to input fields.

## Common Failure Modes

Common failures include over-trusting community posts, ignoring missing dates, and returning an empty risk flag list for thin evidence.

## Safe Defaults

When provenance is unclear, choose `unverified` or `community`, keep the score conservative, and explain what is missing.

## Output Validation Rules

The score must be numeric, flags must come from the enum, and evidence must describe concrete observations rather than broad opinions.
