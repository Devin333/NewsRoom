# Entity Extraction

## Purpose

Extract evidence-backed, normalized entities from collected AI news items.

## Usage

Run after signal collection and before relation building, deduplication, trend analysis, or evidence checking.

## Input

Provide a single item with title and optional summary, content, source, URL, and publication time.

## Output

The skill returns an `entities` array and optional warnings.

## Boundaries

The skill does not enrich entities from external databases or resolve identities beyond the supplied text.

## Examples

See `examples/case_001.*` for a model launch and `examples/case_002.*` for a GitHub project update.
