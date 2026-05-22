## Why

NewsRoom business boards already have domain services, board-specific ranking, cross-board daily intelligence, weekly intelligence, and a framework-quality runtime foundation. The business layer now needs to move from runnable board skeletons to a complete offline product loop that produces artifacts, subscriptions, feedback, learning signals, and human-approved improvement traces for each board without changing framework runtime semantics.

## What Changes

- Add productized per-board workflows, runners, artifact publishers, quality summaries, subscription payloads, feedback events, improvement recommendations, proposals, approved override application, and measurement artifacts for AI News, Project Radar, Paper Radar, and Community Pulse.
- Add a business skill runtime wrapper over existing business skill packages and framework SkillRunner contracts, with deterministic fallbacks for offline tests.
- Add subscription-ready models and payload builders for board and cross-board outputs.
- Add a complete feedback/self-improvement loop that keeps proposals human-approved and applies overrides only after approval.
- Add board eval cases and an eval runner with at least five offline cases per primary board.
- Enhance cross-board intelligence with trend synthesis, conflict detection, subscription aggregation, and improvement aggregation.
- Enhance weekly intelligence with trend, historian, quality, subscription, and improvement outputs while preserving the existing runner API.
- Add productization status documentation and acceptance tests for artifacts and full-loop behavior.

## Capabilities

### New Capabilities
- `business-full-productization`: Productized board runtime covering per-board workflow execution, artifacts, subscriptions, evaluation, feedback closure, improvement proposals, approved overrides, cross-board synthesis, and weekly trend outputs.

### Modified Capabilities
- `business-board-final-target-runtime`: Primary boards gain productized workflow builders, runners, artifacts, subscription payloads, and improvement traces while preserving existing board service behavior.
- `business-cross-board-intelligence`: Cross-board output gains trend synthesis, conflict detection, subscription aggregation, and improvement aggregation.
- `business-foundation-quality-loop`: Feedback closure is extended from feedback and learning signals to recommendations, proposals, approval state, overrides, and measurement.
- `business-interface-board-contracts`: BoardApplicationService gains productized board run entrypoints and cross-board aggregation while preserving existing methods.

## Impact

- Affected code: `business/boards`, `business/foundation/skills`, `business/foundation/feedback`, `business/foundation/subscription`, `business/evaluation`, `interfaces/services/board_service.py`, `docs/business`, and tests.
- No framework runtime, agent runtime, Skill Runtime structure, CLI architecture, live networking, real LLM, or real API-key dependency changes.
- Existing daily and weekly APIs remain compatible; weekly outputs are additive.
