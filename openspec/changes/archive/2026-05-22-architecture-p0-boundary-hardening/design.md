## Context

The repository already has strong framework import boundary tests and a subpackaged Skill Runtime. Remaining P0 work is to remove a small specs-to-runtime dependency, make Skill Runtime ownership executable as tests, and start reducing CLI size without breaking existing callers.

## Goals / Non-Goals

**Goals:**
- Keep `framework.specs` pure of workflow runtime imports.
- Preserve `interfaces.cli.news.main` and `build_parser` behavior.
- Add tests that prevent Skill Runtime from being absorbed into agent or workflow internals.
- Record current infrastructure memory dependency debt without moving those models.

**Non-Goals:**
- No business memory model migration.
- No full CLI rewrite.
- No workflow, artifact, or quality gate behavior changes.

## Decisions

- Terminal status checks stay inside the enum definitions using local terminal sets. This removes runtime coupling without adding a new module.
- `interfaces/cli/news.py` remains the compatibility facade. P0 moves only reports and subscriptions helpers to command modules.
- Skill Runtime tests check imports and implementation ownership instead of moving current code.
- Infrastructure memory dependency debt is documented in architecture tests and left for a later port/DTO migration.

## Risks / Trade-offs

- CLI monkeypatch tests may assume service names live on `interfaces.cli.news` -> preserve facade-level imports and wrappers.
- Moving command handlers can create circular imports -> command modules must import only stable service/model dependencies or receive facade functions.
- Architecture debt whitelist can normalize debt -> include precise paths and TODO naming so it is visible and removable.
