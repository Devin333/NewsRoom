# Repair Prompt

## Goal

Repair a source reliability result so it conforms to the output schema while preserving the original assessment.

## Common Issues

Scores outside `0..1`, unsupported risk flags, missing evidence observations, and empty reasoning summaries are invalid.

## Repair Rules

Clamp scores to the schema range, replace unsupported flags with the nearest allowed flag, and add concise evidence observations from the input.

## Return Format

Return only the repaired JSON object.
