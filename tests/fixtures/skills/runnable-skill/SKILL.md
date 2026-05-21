---
name: runnable-skill
version: 1.0.0
description: Runnable fixture skill for SKILL-02 runtime tests.
category: analysis
tags:
  - runtime
  - fixture
path: tests/fixtures/skills/runnable-skill
input_schema: schemas/input.schema.json
output_schema: schemas/output.schema.json
allowed_tools:
  - schema_validator
risk_level: low
status: active
owner: framework-tests
quality_gates:
  - no_empty_output
  - schema_valid
aliases:
  - runnable
dependencies: []
---

# Runnable Skill

This fixture is used to exercise the generic SkillRunner runtime.
