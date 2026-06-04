# Refactor Completion Checklist

## Completed Items

- Added Harness contracts, ports, state machine, bounded scheduling, RAG, subagent isolation, trace, checkpoint, replay, and skill evolution lifecycle.
- Rebuilt Research under `business/research` without dependencies on old `business.boards`, `interfaces`, or concrete `infrastructure`.
- Added `interfaces/services/research_service.py` and `interfaces/api/routers/research.py`.
- Removed old board, paper, daily, weekly, paper reader, paper ingest, and compatibility adapter services from the backend interface surface.
- Split CLI command registration into `interfaces/cli/commands`.
- Cleaned `interfaces.cli.news` so it only owns parser construction, command registration, dispatch, and `print_json`.
- Updated OpenAPI, SDK tests, MCP tests, CLI tests, API tests, and architecture tests around the Research surface.

## Retired Compatibility Exports

- Old `business/boards`, `business/scoring`, and `business/evaluation` production packages are removed.
- Old `interfaces/api/routers/papers.py`, `interfaces/api/routers/boards.py`, and old paper service modules are removed.
- Old `news run daily`, `news run weekly`, paper ingest queues, and paper reader backfill commands are removed.
- Old `/api/v1/papers*`, `/api/v1/boards*`, `/api/v1/runs/daily`, and `/api/v1/runs/weekly` routes are not registered.

## Final Acceptance Items

- OpenSpec change `harness-research-runtime` validates with `openspec validate --strict`.
- `python -m scripts.dev compile` passes.
- `python -m scripts.dev test` passes.
- `python -m scripts.dev smoke` passes with the backend smoke scope.
- The OpenSpec change is archived after all tasks are complete.

## Test Commands

```powershell
python -m scripts.dev compile
python -m scripts.dev test
python -m scripts.dev smoke
openspec validate harness-research-runtime --strict
```

## Not In Scope

- UI migration.
- Old paper UI compatibility adapters.
- Reintroducing daily, weekly, board, or paper ingest backend compatibility routes.
