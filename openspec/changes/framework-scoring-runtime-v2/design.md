## Context

`framework-scoring-runtime` introduced a working v1 scoring runtime and a board adapter, but the PRD v2 classified design expects `framework/scoring` to be a subsystem with clear package ownership. This change builds on v1 without removing or breaking its top-level imports.

## Goals / Non-Goals

**Goals:**

- Add the classified `framework/scoring` subpackage layout from the v2 PRD.
- Preserve existing imports such as `framework.scoring.models`, `framework.scoring.scorer`, and `from framework.scoring import ScoringRuntime`.
- Add v2 helper APIs and registry extension points needed for future scoring migrations.
- Add a `business/scoring` migration layer without switching existing board workflows to it.

**Non-Goals:**

- No breaking import-path migration.
- No dependency from framework scoring to business or memory runtimes.
- No rewrite of existing board service or `_intelligence.py` execution flow.
- No external ML, storage, database, or web console integration.

## Decisions

- Keep top-level files as compatibility wrappers. The real implementations move into classified packages, while wrapper modules re-export the same names for old tests and callers.
- Treat v2 algorithm classes as aliases/subclasses of existing scorer behavior. This preserves stable IDs like `weighted_linear` while exposing the v2 `ScoringAlgorithm` naming.
- Expand registry rather than replacing it. `register_scorer` and `require_scorer` stay available; `register_algorithm` and `require_algorithm` become first-class aliases backed by the same algorithm map.
- Put business migration helpers under `business/scoring`, not `framework/scoring/adapters`, because board-card semantics belong to business.
- Keep tests for both compatibility and v2 classified paths so future cleanup can happen intentionally.

## Risks / Trade-offs

- [Risk] Duplication between compatibility wrappers and classified modules. Mitigation: wrappers should only import/re-export, not reimplement logic.
- [Risk] Package registration drift in `pyproject.toml`. Mitigation: explicitly list all new `framework.scoring.*` and `business.scoring.*` packages.
- [Risk] Business feature builders become a second source of scoring semantics. Mitigation: keep them thin and based on existing board intelligence helper functions.
