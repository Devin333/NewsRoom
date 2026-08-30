---
name: event-deduplication
version: "1.0.0"
description: >-
  Group multiple news items, papers, GitHub updates, or community posts that
  refer to the same underlying event. Use after entity extraction and before
  ranking, trend analysis, timeline building, or report writing.
category: relation
tags:
  - deduplication
  - event
  - clustering
  - relation
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

# Event Deduplication

## Purpose

Group items that refer to the same underlying news event so downstream ranking, trend analysis, and report writing do not over-count repeated coverage.

## When to Use

Use after entity extraction and before event ranking, timeline building, trend analysis, or report writing.

## Inputs

Provide an `items` array with each item carrying an id, title, optional summary, source, publication time, URL, and extracted entities.

## Outputs

Return `event_groups` with canonical item selection and optional `duplicate_pairs` that explain pair-level same-event decisions.

## Method

Compare core entities, event action, timing, source role, and claim substance. Merge coverage of the same announcement, release, paper, or repository update, and keep separate events distinct when the product, claim, or action differs.

## Instructions

Choose the canonical item with the clearest original source or most complete evidence. Use lower confidence when overlap is partial.

## Quality Gates

The output must be schema-valid, include all input item ids in at least one event group when possible, and avoid merging different product launches.

## Failure Modes

When items are too ambiguous to merge, keep them in separate groups and explain uncertainty in `merge_reason` or pair `reason`.

## Examples

An official blog and media story about the same model launch should merge. Two different products announced by the same company should remain separate.

## Do Not

Do not infer hidden relationships, browse for missing context, or merge items solely because they mention the same company.
