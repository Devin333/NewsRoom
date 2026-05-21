## Context

Existing tests cover broad final closure, but this change adds explicit acceptance targets from the PRD and raw payload recursion checks.

## Design

- Add service-level final business run result test under interface services.
- Add business acceptance test with minimal raw items.
- Add recursive no raw payload contract for final run, board workflow results, board cards, cross-board paths, and cross-board insights.

## Constraints

- Prefer tests only. Keep production changes minimal and compatibility-preserving.
