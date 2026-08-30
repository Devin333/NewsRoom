# Evidence Checking

## Purpose

Verify factual claims against provided source text and citations.

## Usage

Run before report writing, publishing, ranking, or any output that exposes factual claims.

## Input

Provide claim objects and source objects with stable ids and source text.

## Output

The skill returns per-claim support status, source ids, evidence spans, explanations, suggested rewrites, and summary counts.

## Boundaries

The skill does not fetch new sources, create citations, or resolve disputes outside the provided evidence.

## Examples

See `examples/case_001.*` for a supported claim and `examples/case_002.*` for an over-broad claim marked unclear.
