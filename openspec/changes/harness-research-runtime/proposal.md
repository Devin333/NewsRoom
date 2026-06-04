## Why

NewsRoom has accumulated multiple partially overlapping agent, workflow, board, reader, and paper runtime paths. The next architecture needs a single Harness Control Plane before rebuilding Research, so routing, quality gates, memory writes, skill evolution, replay, and deletion decisions are deterministic and reviewable.

## What Changes

- **BREAKING**: Establish `framework/harness` as the only workflow decision-making control plane for the new runtime; legacy agent harness, workflow shortcuts, and board-specific control flows become adapt/delete candidates.
- Add bounded `PLAN -> EXECUTE -> VERIFY` runtime requirements with explicit budgets, deterministic gates, durable events, checkpointing, replay, and controlled replan/retry/halt outcomes.
- Define Harness-owned ports for LLM, tools, memory, skills, artifacts, events, workers, governance, context assembly, subagents, and bounded RAG.
- Rebuild Research under `business/research` as a clean domain that does not depend on `business/boards/paper_radar`, `interfaces`, or `infrastructure`.
- Add Harness-controlled skill evolution requirements: LLMs may propose candidates or patches, while Harness owns validation, held-out evals, promotion, release, and rollback.
- Mark obsolete framework, business, interface, and test assets for staged cleanup; stage 0 only records the inventory and does not delete runtime code.
- Keep UI and frontend migration out of scope for this change.

## Capabilities

### New Capabilities

- `harness-runtime`: Harness Control Plane contracts, bounded state machine, scheduler, ports, subagent isolation, context assembly, bounded RAG, trace, checkpoint, and replay.
- `research-runtime`: Research domain model, product scenarios, single-paper loop, reader repair memory, backend service, and API boundary.
- `harness-skill-evolution`: Harness-controlled skill candidate, validation, evaluation, promotion, versioned release, and rollback lifecycle.
- `legacy-runtime-cleanup`: Staged deletion and adaptation rules for old framework, board, paper, interface, and test assets that do not serve Harness + Research.

### Modified Capabilities

- None. Existing capabilities remain historical context until later phases adapt or retire them through this change.

## Impact

- Affected code and docs: `framework`, `business`, `interfaces`, `tests`, `openspec/specs`, `docs/architecture`, and `docs/prd/harness-research-runtime`.
- New OpenSpec change root: `openspec/changes/harness-research-runtime`.
- New target runtime paths include `framework/harness`, `business/research`, `interfaces/services/research_service.py`, `interfaces/api/routers/research.py`, and focused tests under `tests/framework/harness`, `tests/business/research`, and `tests/interfaces/research`.
- Existing useful framework assets under `framework/llm`, `framework/tool`, `framework/memory`, `framework/skills`, `framework/artifacts`, `framework/events`, `framework/workers`, `framework/scoring`, `framework/governance`, and `framework/shared` are expected to be kept or adapted rather than rewritten.
- Old paper, board, compatibility, and UI-facing assets are not deleted in stage 0; they are inventoried for stages 8 and 9.
