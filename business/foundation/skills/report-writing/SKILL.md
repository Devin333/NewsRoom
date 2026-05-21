---
name: report-writing
version: "1.0.0"
description: >-
  Write structured, evidence-aware Markdown reports from ranked and verified
  AI news events, project signals, paper signals, community signals, and trend
  analyses. Use as the final output step before artifact publishing.
category: output
tags:
  - report
  - writing
  - markdown
  - citation
  - briefing
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

# Report Writing

## Purpose

Write structured, evidence-aware Markdown reports from ranked and verified AI news events and supporting trend analysis.

## When to Use

Use as the final output step before artifact publishing or user delivery.

## Inputs

Provide report metadata, verified items, trend analyses, citations, and any evidence warnings that should affect wording.

## Outputs

Return `markdown_report`, `summary`, structured `sections`, `citations`, and `warnings`.

## Method

Select verified items, organize them into concise sections, write factual Markdown with citations, preserve item ids, and surface unresolved evidence as warnings.

## Instructions

Keep claims tied to citations, use cautious wording for unclear evidence, and avoid unsupported synthesis.

## Quality Gates

The report must be non-empty Markdown, every section must reference item ids, and citations must include item id, URL, and source name.

## Failure Modes

When important evidence is unclear, write the report with warnings rather than omitting the uncertainty.

## Examples

A technical daily with two verified items should produce a concise Markdown briefing. A report with unclear evidence should include warnings and cautious wording.

## Do Not

Do not invent citations, browse for missing links, write unsupported recommendations, or hide unresolved evidence issues.
