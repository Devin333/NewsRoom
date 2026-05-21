---
name: trend-analysis
version: "1.0.0"
description: >-
  Analyze the momentum, novelty, and potential impact of events across AI news,
  papers, GitHub projects, and community signals. Use after deduplication and
  evidence checking to decide what deserves ranking, watchlist tracking, or
  report coverage.
category: analysis
tags:
  - trend
  - momentum
  - novelty
  - impact
  - watchlist
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

# Trend Analysis

## Purpose

Analyze momentum, novelty, and likely impact for deduplicated AI news events so ranking and watchlist decisions can use a consistent signal.

## When to Use

Use after event deduplication and evidence checking, before ranking, watchlist tracking, or report coverage decisions.

## Inputs

Provide event groups with items, source counts, evidence status, community signals, repository signals, or any supplied metrics.

## Outputs

Return `event_analyses` with trend score, momentum, novelty, impact areas, why-it-matters text, watchlist recommendation, and reasoning summary.

## Method

Score each event by source diversity, evidence strength, recency, independent pickup, technical novelty, concrete impact, and community or repository momentum.

## Instructions

Favor evidence-backed, multi-source, technically meaningful events. Penalize single-source marketing items and unsupported breakthrough claims.

## Quality Gates

Each event analysis must include an event id, score between `0` and `1`, enum values for momentum, novelty, recommendation, and a non-empty reasoning summary.

## Failure Modes

When evidence is weak or signals are sparse, return `monitor` or `ignore` rather than escalating.

## Examples

Multiple independent sources around an agent framework update can be `track`. A lone marketing blog with no secondary signal should have a low trend score.

## Do Not

Do not rank by hype alone, invent metrics, or treat a claimed breakthrough as proven impact without evidence.
