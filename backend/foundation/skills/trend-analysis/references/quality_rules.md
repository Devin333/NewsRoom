# Quality Rules

## Required Checks

Validate schema, ensure every event id comes from input, check score bounds, and verify recommendation is consistent with evidence quality.

## Common Failure Modes

Common failures include over-weighting community hype, ignoring primary sources, and labeling every model update as breakthrough.

## Safe Defaults

When signals are weak, choose `monitor` or `ignore` and explain which evidence is missing.

## Output Validation Rules

Every event analysis must contain non-empty `impact_area`, `why_it_matters`, and `reasoning_summary`.
