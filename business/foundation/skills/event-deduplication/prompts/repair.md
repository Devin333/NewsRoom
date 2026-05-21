# Repair Prompt

## Goal

Repair an event deduplication result so group and pair objects match the schema and refer only to input ids.

## Common Issues

Missing canonical ids, empty item groups, unsupported field names, and pair decisions without confidence are invalid.

## Repair Rules

Remove unknown ids, add canonical ids from group members, clamp confidence to a reasonable numeric value, and keep separate groups when a merge is not justified.

## Return Format

Return only the repaired JSON object.
