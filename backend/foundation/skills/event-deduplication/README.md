# Event Deduplication

## Purpose

Group collected items by underlying event and select canonical evidence for each group.

## Usage

Run after entity extraction and before ranking, timeline building, trend analysis, or report writing.

## Input

Provide an array of items with ids, titles, summaries, source metadata, publication dates, and optional extracted entities.

## Output

The skill returns event groups and optional duplicate-pair decisions.

## Boundaries

The skill does not fetch missing articles, rank event importance, or mutate source items.

## Examples

See `examples/case_001.*` for a same-event merge and `examples/case_002.*` for separate events from the same company.
