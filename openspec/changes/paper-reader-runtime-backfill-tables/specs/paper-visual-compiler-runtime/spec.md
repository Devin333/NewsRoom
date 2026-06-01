## MODIFIED Requirements

### Requirement: Compilation runs in background tasks
The system SHALL compile papers through worker tasks and SHALL provide a backfill task that keeps published paper Reader artifacts complete over time.

#### Scenario: Ingest enqueues visual compile
- **WHEN** a paper ingest completes with published paper IDs
- **THEN** the system enqueues `papers.visual_compile` for each published paper without blocking ingest completion.

#### Scenario: Backfill expands missing Reader artifacts
- **WHEN** `papers.visual_compile_backfill` is processed
- **THEN** the handler scans real published papers and enqueues `papers.visual_compile` for papers with no compiled status, non-compiled status, missing published document, or missing/passing source-comparison proof.

#### Scenario: Compiled papers are skipped unless forced
- **WHEN** backfill sees a paper with a published compiled document and passing source-comparison report
- **THEN** it skips the paper unless the backfill payload sets `force` to true.

#### Scenario: Document read does not trigger compile
- **WHEN** a client requests a paper document
- **THEN** the API reads the latest published artifact/status and does not enqueue or execute compilation.

### Requirement: Paper document APIs expose compiled artifacts safely
The system SHALL expose APIs for published document reads, compile status, manual compile enqueue, visual compile backfill enqueue, visual assets, and source previews.

#### Scenario: Visual compile backfill can be triggered through ops API
- **WHEN** an operator posts to the visual compile backfill ops endpoint
- **THEN** the API enqueues `papers.visual_compile_backfill` or starts a local background fallback with explicit run metadata.

#### Scenario: Backfill trigger validates limits
- **WHEN** an operator supplies a non-positive limit
- **THEN** the API rejects the request without enqueueing work.

## ADDED Requirements

### Requirement: Reader visual compile backfill is schedulable
The system SHALL provide a schedule helper for periodic `papers.visual_compile_backfill` tasks using the existing scheduler runtime.

#### Scenario: Periodic schedule enqueues backfill task
- **WHEN** a due Paper Reader backfill schedule is evaluated
- **THEN** the scheduler enqueues a `papers.visual_compile_backfill` task onto the paper queue with the configured limit and force flag.

### Requirement: Structured table assets remain reader-native
The system SHALL represent source-package tables as structured Reader table models plus HTML assets and SHALL validate the model before publication.

#### Scenario: TeX table produces structured style metadata
- **WHEN** a TeX table contains row colors, cell colors, booktabs rules, `cmidrule`, `multicolumn`, or `multirow`
- **THEN** the compiler emits a `tableModel` carrying row rules, row/cell color classes, span values, alignments, and sanitized inline HTML.

#### Scenario: Table without structured metadata is blocked
- **WHEN** a table visual asset is stored as structured HTML but lacks `tableModel` or `tableHtml`
- **THEN** Asset Gate records `table_asset_model_missing` and prevents publication.
