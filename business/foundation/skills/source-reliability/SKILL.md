---
name: source-reliability
version: "1.0.0"
description: >-
  Assess the reliability of a source or publisher for AI news, official blogs,
  research papers, GitHub repositories, and community posts. Use before ranking,
  deduplication, evidence checking, or report writing when source trust must be
  converted into a structured score and risk flags.
category: source
tags:
  - source
  - reliability
  - trust
  - risk
  - ai-news
input_schema: schemas/input.schema.json
output_schema: schemas/output.schema.json
allowed_tools:
  - llm
  - schema_validator
risk_level: medium
owner: business-foundation
quality_gates:
  - schema_valid
  - no_empty_output
---

# Source Reliability

## Purpose

Convert source trust signals into a structured reliability score, source tier, risk flags, and evidence observations that downstream ranking and reporting can reuse.

## When to Use

Use this skill before event ranking, event deduplication, evidence checking, or report writing whenever a source, publisher, post, paper host, or repository must be compared against other signals.

## Inputs

Provide a `source` object with name, URL, publisher type, and optional reputation, plus a `content` object with at least a title and any available author, date, URL, and raw text.

## Outputs

Return `reliability_score`, `source_tier`, `risk_flags`, `reasoning_summary`, and field-level `evidence` observations.

## Method

Classify publisher type first, then adjust for provenance, author/date completeness, original evidence, conflict-of-interest risk, and language that looks promotional or rumor-driven.

## Instructions

Prefer primary sources for official announcements, research artifacts, repository release notes, and direct author publications. Penalize anonymous posts, aggregation without original links, missing dates, and claims that cannot be traced to source material.

## Quality Gates

The output must match the schema, include a non-empty reasoning summary, and include at least one evidence observation for any score below `0.95`.

## Failure Modes

Return `unverified` with `unknown_source` or `low_evidence` when the source cannot be identified, the content is too thin, or the claim is only repeated by community posts.

## Examples

An official vendor blog with author and publication date should usually be `primary` with a score above `0.9`. A community rumor thread without an author or original citation should be `community` with rumor and low-evidence flags.

## Do Not

Do not browse the web, infer unstated credentials, upgrade community rumors into primary evidence, or change the meaning of the supplied content.
