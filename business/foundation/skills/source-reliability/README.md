# Source Reliability

## Purpose

Assess whether a source can be trusted as primary, secondary, community, or unverified evidence.

## Usage

Run this skill after collecting an item and before ranking, deduplication, evidence checking, or report writing.

## Input

Provide source metadata and content metadata. Include author, date, URL, raw text, and historical context when available.

## Output

The skill returns a reliability score, source tier, risk flags, reasoning summary, and evidence observations.

## Boundaries

The skill does not fetch webpages, update source registries, or decide final report ranking.

## Examples

See `examples/case_001.*` for an official blog and `examples/case_002.*` for a community rumor.
