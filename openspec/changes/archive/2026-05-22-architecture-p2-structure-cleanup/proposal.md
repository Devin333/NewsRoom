## Why

After boundary hardening and hotspot splitting, remaining cleanup should reduce noise and prevent future structural drift without large semantic migrations.

## What Changes

- Remove tracked or present `__pycache__` artifacts from source trees.
- Make `framework/workflow/specs` a compatibility facade for SkillStepSpec.
- Add tests that discourage uncontrolled root package export growth.
- Add light documentation indexes for framework improvement, skill, and OpenSpec spec docs.
- Record a follow-up migration path for infrastructure memory/graph business-model dependencies.

## Capabilities

### New Capabilities
- `structure-cleanup-governance`: Rules for source-tree cleanliness, compatibility facades, export-surface growth, and documentation indexes.

### Modified Capabilities
- `workflow-runtime-target-closure`: Workflow spec compatibility remains available while canonical spec ownership is clarified.

## Impact

- Affects compatibility modules, architecture tests, documentation indexes, and cleanup scripts/tests.
- No runtime behavior or storage schema migration.
