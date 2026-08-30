---
name: entity-extraction
version: "1.0.0"
description: >-
  Extract normalized entities from AI news, papers, GitHub projects, official
  blogs, and community posts. Use after signal collection and before relation
  building, deduplication, trend analysis, or evidence checking.
category: extraction
tags:
  - entity
  - extraction
  - normalization
  - ai-news
  - paper
  - github
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

# Entity Extraction

## Purpose

Extract normalized entities from news items so relation builders, deduplicators, trend analysis, and evidence checks can reason over consistent names.

## When to Use

Use this skill after signal collection and before any workflow step that needs structured companies, products, models, repositories, papers, metrics, people, institutions, frameworks, or events.

## Inputs

Provide one `item` with a title and optional summary, content, URL, source name, and publication date.

## Outputs

Return an `entities` list with name, normalized name, type, aliases, evidence span, and confidence, plus optional warnings.

## Method

Read title, summary, and content together, extract only entities supported by explicit spans, normalize surface forms, and preserve aliases when abbreviations or repository slugs appear.

## Instructions

Prefer canonical public names, avoid duplicate aliases, and set lower confidence when a name is implied but not directly stated.

## Quality Gates

Every entity must include an evidence span from the input. Outputs must pass schema validation and should not be empty when the item clearly names entities.

## Failure Modes

If the item is too short or ambiguous, return low-confidence entities with warnings rather than inventing missing names.

## Examples

A model release should include company, model, and event entities. A repository update should include repo, framework, and metric entities when present in the text.

## Do Not

Do not infer private entities, browse for missing metadata, or extract generic technology terms that are not meaningful entities in the item.
