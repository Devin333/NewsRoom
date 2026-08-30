# Repair Prompt

## Goal

Repair an entity extraction result so each entity is schema-valid and evidence-backed.

## Common Issues

Missing evidence spans, unsupported entity types, duplicate aliases, confidence outside `0..1`, and invented normalized names are invalid.

## Repair Rules

Remove unsupported entities, map types to the nearest enum value, clamp confidence, and preserve only aliases found or clearly implied by the input text.

## Return Format

Return only the repaired JSON object.
