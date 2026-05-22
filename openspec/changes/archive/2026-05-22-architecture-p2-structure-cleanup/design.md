## Context

Source scans currently include `__pycache__` artifacts, `framework/workflow/specs` contains a concrete skill step spec, and root package exports are broad compatibility surfaces. Documentation folders also need lightweight navigation.

## Goals / Non-Goals

**Goals:**
- Remove generated cache noise from source scans.
- Clarify canonical spec ownership while preserving old imports.
- Prevent accidental root export growth.
- Add documentation indexes and future migration notes.

**Non-Goals:**
- No deletion of compatibility imports.
- No storage or memory model migration.
- No behavior changes to workflow specs.

## Decisions

- Move `SkillStepSpec` canonical definition to `framework.specs.skill_step` and re-export it from `framework.workflow.specs`.
- Add tests that pin compatibility facades rather than pruning existing exports.
- Add concise docs indexes instead of reorganizing documentation files.
- Write future infrastructure memory dependency migration guidance as documentation/OpenSpec follow-up, not code movement.

## Risks / Trade-offs

- Moving `SkillStepSpec` can break imports -> keep `framework.workflow.specs.skill_step` as a direct re-export module.
- Export tests can be brittle -> check for bounded growth and key compatibility names, not exact full lists.
- Removing cache files can touch untracked files only -> verify git status before and after.
