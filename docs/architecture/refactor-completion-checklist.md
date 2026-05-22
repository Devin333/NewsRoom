# Refactor Completion Checklist

## Completed Items

- Documented project and framework boundaries.
- Split CLI command registration into `interfaces/cli/commands`.
- Kept `interfaces.cli.news` as the parser and dispatch facade.
- Split `RunApplicationService` into daily, weekly, live smoke, approval resume, persistence, and resolution services.
- Extracted daily intelligence connector bundle, connector factory, dependency bundle, and runtime assembly.
- Added `infrastructure/storage/persistence` and kept old repository import compatibility.
- Switched package configuration to setuptools package auto discovery.

## Compatibility Exports

- `interfaces.cli.news` still exports legacy service symbols used by tests and scripts.
- `interfaces.cli.commands.reports` and `interfaces.cli.commands.subscriptions` keep their handler helpers.
- `interfaces.services.run_service` still exports `RunApplicationService`, `LiveSmokeResult`, approval resume helpers, workflow builders, `repository_from_env`, and `persist_run_result`.
- `business.boards.cross_board.workflows.daily_intelligence.runtime_assembly` still exports `DailySourceRuntimeAssembly`, `build_daily_source_runtime_assembly`, and `apply_daily_source_runtime_assembly`.
- `infrastructure.storage.repository` still exports persistence records, repository factory, local JSON adapter, and run-result persistence helpers.

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
