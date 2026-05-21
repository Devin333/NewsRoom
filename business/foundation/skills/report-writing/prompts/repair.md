# Repair Prompt

## Goal

Repair a report-writing result so Markdown, sections, citations, and warnings match the output schema.

## Common Issues

Missing citations, sections without item ids, empty Markdown, and absent warnings for unclear evidence are invalid.

## Repair Rules

Add citations from input items, attach item ids to relevant sections, preserve cautious wording, and keep all required fields present.

## Return Format

Return only the repaired JSON object.
