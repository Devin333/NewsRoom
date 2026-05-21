---
name: valid-skill
version: 1.2.3
description: >-
  A valid fixture skill used by framework skill package tests.
category: extraction
tags:
  - Entity
  - extraction
path: tests/fixtures/skills/valid-skill
input_schema: schemas/input.schema.json
output_schema: schemas/output.schema.json
allowed_tools:
  - schema_validator
risk_level: low
status: active
owner: framework-tests
quality_gates:
  - schema-valid
aliases:
  - entity-extract
dependencies: []
---

# Valid Skill

This fixture is intentionally small.
