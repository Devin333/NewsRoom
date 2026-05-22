# Refactor Completion Checklist

## Completed Items

- Skill Runtime subpackaged under `framework/skills`.
- Switched package configuration to setuptools package auto discovery.
- Split CLI command registration into `interfaces/cli/commands`.
- Split `RunApplicationService` into daily, weekly, live smoke, approval resume, persistence, and resolution services.
- Slimmed `RunApplicationService` facade so business workflow runner selection and approval resume resolution live in focused services.
- Extracted daily intelligence connector bundle, connector factory, dependency bundle, and runtime assembly.
- Added `infrastructure/storage/persistence` and kept old repository import compatibility.
- Cleaned `interfaces.cli.news` so it only owns parser construction, command registration, dispatch, and `print_json`.
- Added architecture boundary documents for project, framework, interface, business, and persistence layers.
- Added targeted CLI entrypoint, package, and static boundary tests.

## Compatibility Exports

- `interfaces.cli.news` intentionally does not export service, framework, business, or infrastructure symbols.
- `interfaces.cli.commands.reports` and `interfaces.cli.commands.subscriptions` keep their handler helpers for focused command tests.
- `interfaces.services.run_service` still exports `RunApplicationService`, `LiveSmokeResult`, approval resume helpers, workflow builders, `repository_from_env`, and `persist_run_result`.
- `business.boards.cross_board.workflows.daily_intelligence.runtime_assembly` still exports `DailySourceRuntimeAssembly`, `build_daily_source_runtime_assembly`, and `apply_daily_source_runtime_assembly`.
- `infrastructure.storage.repository` still exports persistence records, repository factory, local JSON adapter, and run-result persistence helpers.

## Final Acceptance Items

- `news.py` import cleanup complete.
- `run_service.py` facade slimming complete.
- Architecture boundary documentation complete.
- Targeted CLI, service, package, and architecture tests added.

## Remaining Items

- No known architecture cleanup items remain in this package.

## Test Commands

```powershell
python -m compileall -q framework business interfaces infrastructure
pytest tests/framework -q
pytest tests/business -q
pytest tests/interfaces -q
pytest tests/infrastructure -q
pytest tests/interfaces/cli -q
pytest tests/interfaces/services -q
pytest tests/business/boards/cross_board/workflows/daily_intelligence -q
pytest tests/infrastructure/storage -q
python -m scripts.dev compile
python -m scripts.dev test
python -m scripts.dev smoke
```

## Not In Scope

- No LangGraph dependency.
- No framework evolution or harness sidecar.
- No business semantic changes.
- No business skill content moved into framework Skill Runtime.
- No scoring/governance merge.
- No CLI direct access to executors, stores, or runners.
