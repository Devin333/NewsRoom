## ADDED Requirements

### Requirement: Reader artifact review runs in a framework subagent
The system SHALL provide a framework-level reviewer for Research Reader compiled artifacts that evaluates image, table, equation, and symbol quality gates without relying on AI-generated paper body content.

#### Scenario: Review produces gate summaries
- **WHEN** a `PaperDocument` and `PaperAssetManifest` are reviewed
- **THEN** the reviewer SHALL return `passed`, `errors`, `warnings`, and a `gates` summary for image, table, equation, and symbol gates
- **AND** each issue SHALL include a stable fingerprint and locator context including paper id and available block, asset, surface, or origin fields.

### Requirement: Review issue memory is durable and reusable
The system SHALL persist every artifact review issue to a durable local memory journal keyed by issue fingerprint.

#### Scenario: A repeated issue is reviewed
- **WHEN** a new review emits an issue whose fingerprint already exists in memory
- **THEN** the review result SHALL include a memory match with previous locator and seen-count context
- **AND** the journal SHALL retain recent locator occurrences so repeated failures can be traced back to prior blocks, assets, or surfaces
- **AND** the journal SHALL update the issue's last-seen metadata without blocking compilation if memory persistence fails.

### Requirement: Reader-facing TeX artifacts are source-first and cleaned at parse time
The source-first TeX compiler SHALL prevent parser syntax from leaking into reader-facing blocks.

#### Scenario: Top-level tabular or link table appears outside a table environment
- **WHEN** the TeX body contains a top-level `tabular`, `tabularx`, or `array` block, including one wrapped by `center`
- **THEN** the compiler SHALL emit a table artifact or skip unsupported structure
- **AND** it SHALL NOT emit table alignment tokens such as `rll &` as paragraph text.

#### Scenario: Equations and table math contain formatting wrappers
- **WHEN** equations or table cells include TeX text wrappers, URL commands, fraction commands, or size environments
- **THEN** reader-facing text and table HTML SHALL preserve readable source content without exposing unsupported raw parser syntax.

### Requirement: Paper detail drawer stays a side panel
The Research paper detail drawer SHALL remain a side drawer and SHALL NOT occupy the entire viewport on wide screens.

#### Scenario: Drawer opens from a paper title
- **WHEN** a user opens paper details from the Research list
- **THEN** the drawer width SHALL stay within a bounded side-panel width on desktop and mobile viewports
- **AND** it SHALL leave visible page context outside the drawer.
