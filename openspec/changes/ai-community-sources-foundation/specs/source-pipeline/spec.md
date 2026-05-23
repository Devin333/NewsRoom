## ADDED Requirements

### Requirement: AI community source taxonomy
The source pipeline SHALL support the final AI Community Sources taxonomy for configured sources.

#### Scenario: Config uses final semantic categories
- **WHEN** tracked source config is loaded
- **THEN** every configured category is one of `research`, `open_source`, `model_platform`, `official_blog`, `agent_framework`, `developer_discussion`, or `engineering_practice`
- **AND** Chinese sources are represented with `language: zh` and `region: cn`
- **AND** `chinese_ai_media` is not accepted as a category.

### Requirement: AI community source metadata validation
Source registry validation SHALL validate AI community source metadata without breaking existing source shape.

#### Scenario: Category and priority are validated
- **WHEN** source validation runs
- **THEN** invalid source categories and invalid `metadata.priority` values are errors
- **AND** missing `metadata.signal_kind` is a warning
- **AND** `metadata.group` that differs from category is a warning.

### Requirement: Source connector routing
The source pipeline SHALL route configured source definitions through a reusable source connector router.

#### Scenario: Router dispatches by source type
- **WHEN** a supported source type is fetched through the router
- **THEN** the corresponding connector is called
- **AND** the router returns `(items, errors)` using the existing `RawSourceItem` and `SourceError` contract.

### Requirement: Generic source fetch service
The source application service SHALL expose generic fetch methods for source, category, priority, and topic selection.

#### Scenario: Fetch by topic includes selection report
- **WHEN** topic fetch is requested
- **THEN** sources are selected through `SourceRegistry.select_sources_with_report`
- **AND** the batch result includes the selection report.

#### Scenario: Health gating prevents batch fetch
- **WHEN** a source health decision says not to fetch and force is false
- **THEN** the service returns a skipped source fetch result
- **AND** the source connector is not called.

### Requirement: Source CLI generic fetch commands
The source CLI SHALL expose generic source fetch commands through the application service.

#### Scenario: JSON batch output is contract-shaped
- **WHEN** `news sources fetch-category`, `fetch-priority`, or `fetch-topic` runs with `--json`
- **THEN** output includes `ok`, `source_count`, `item_count`, `error_count`, `skipped_count`, and `results`.
