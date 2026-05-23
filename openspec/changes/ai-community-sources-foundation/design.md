## Design

The tranche keeps the existing source pipeline boundaries and extends them from the inside out.

`configs/sources.yaml` remains the single executable source registry file. Entries use existing PRD-shaped sections and existing `SourceDefinition` fields. Category semantics move to the final seven values, while `language`, `region`, and `metadata.group` carry language, geography, and product grouping.

`business/layers/signal/source_catalog.py` provides stable constants and normalization helpers. Validation uses those helpers but remains backward-compatible where possible: missing `metadata.signal_kind` is a warning, and `metadata.group` mismatch is a warning. Invalid categories and priorities are errors; `chinese_ai_media` is rejected explicitly.

`business/layers/signal/source_router.py` dispatches by `SourceDefinition.source_type` and shields application services from connector-specific imports and branching. The router accepts business-layer `SourceDefinition`, converts to the existing infrastructure source model before connector calls, and returns the current infrastructure `RawSourceItem` / `SourceError` tuple shape used by source preview DTOs.

`SourceApplicationService` owns health gating and batch orchestration. Generic fetch methods look up or select sources through `SourceRegistry`, ask `BasicSourceHealthManager.fetch_decision()` unless `force=True`, call the router, and record source success/failure using the existing health manager. Existing `fetch_arxiv()` and `fetch_github_releases()` remain compatible wrappers.

The CLI remains an interface adapter. It calls only `SourceApplicationService`, supports both human-readable and JSON output, and treats external fetch errors as contract-shaped result content rather than command crashes.
