---
name: evidence-checking
version: "1.0.0"
description: >-
  Verify whether generated claims are supported, contradicted, or unclear based
  on provided source texts and citations. Use before report writing, publishing,
  ranking, or any user-visible output that contains factual claims.
category: quality
tags:
  - evidence
  - citation
  - verification
  - claim
  - quality
input_schema: schemas/input.schema.json
output_schema: schemas/output.schema.json
allowed_tools:
  - llm
  - schema_validator
risk_level: medium
owner: business-foundation
quality_gates:
  - schema_valid
  - evidence_required
  - no_empty_output
---

# Evidence Checking

## Purpose

Verify whether generated claims are supported, contradicted, or unclear based on supplied source texts and citations.

## When to Use

Use before report writing, publishing, ranking, alerting, or any user-visible output that contains factual claims.

## Inputs

Provide `claims` with claim ids and text, plus `sources` with source ids, text, URLs, and optional source names.

## Outputs

Return per-claim results with status, supporting and contradicting source ids, evidence spans, explanations, suggested rewrites, and summary counts.

## Method

Compare each claim against source text, identify exact support or contradiction, mark over-broad or insufficiently sourced claims as unclear, and suggest conservative rewrites when useful.

## Instructions

Treat absence of evidence as `unclear`, not `supported`. Use `contradicted` only when a source directly conflicts with the claim.

## Quality Gates

Every claim result must include an explanation and at least empty arrays for supporting and contradicting source ids.

## Failure Modes

When sources are too thin, return `unclear` with a suggested rewrite that narrows the claim to what the evidence states.

## Examples

A claim that exactly matches a source sentence is supported. A claim that adds unsupported magnitude, timing, or certainty is unclear unless contradicted.

## Do Not

Do not browse for external evidence, invent citations, or turn unclear claims into supported claims because they sound plausible.
