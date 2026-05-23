## 1. OpenSpec And Documentation

- [x] 1.1 Add OpenSpec proposal, design, tasks, and source-pipeline spec delta.
- [x] 1.2 Add the final AI Community Sources PRD under `docs/prd/` and update the docs index if present.

## 2. Source Taxonomy And Config

- [x] 2.1 Rewrite `configs/sources.yaml` using only the final seven AI community source categories.
- [x] 2.2 Add source catalog constants and validation helpers.
- [x] 2.3 Enhance `SourceRegistry.validate()` for category, priority, group, and signal kind metadata.

## 3. Routing And Service Fetch APIs

- [x] 3.1 Add `SourceConnectorRouter` with supported source type dispatch and fake-connector tests.
- [x] 3.2 Extend `SourceApplicationService` with source, category, priority, and topic fetch methods.
- [x] 3.3 Preserve arXiv and GitHub compatibility wrapper behavior.

## 4. CLI Surfaces

- [x] 4.1 Add generic source fetch, inspect, categories, and priorities CLI commands.
- [x] 4.2 Keep existing source CLI commands compatible.

## 5. Validation

- [x] 5.1 Add focused tests for catalog, config, registry validation, router, service, and CLI behavior.
- [x] 5.2 Run OpenSpec validation, compile checks, CLI validation, and focused pytest suites.
