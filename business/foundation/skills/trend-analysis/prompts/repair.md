# Repair Prompt

## Goal

Repair a trend analysis result so each event analysis is complete and schema-valid.

## Common Issues

Invalid enum values, trend scores outside `0..1`, empty impact areas, and missing reasoning summaries are invalid.

## Repair Rules

Map enums to allowed values, clamp scores, add concise impact areas from input, and keep recommendations conservative when evidence is weak.

## Return Format

Return only the repaired JSON object.
