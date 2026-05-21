# Repair Prompt

## Goal

Repair an evidence checking result so each claim result is complete and schema-valid.

## Common Issues

Missing summary counts, unsupported status values, missing suggested rewrites, and evidence spans without source ids are invalid.

## Repair Rules

Normalize status to `supported`, `contradicted`, or `unclear`; recompute summary counts; and keep arrays present even when empty.

## Return Format

Return only the repaired JSON object.
