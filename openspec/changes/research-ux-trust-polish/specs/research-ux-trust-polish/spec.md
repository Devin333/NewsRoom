## ADDED Requirements

### Requirement: Product-facing Research data states
Research pages SHALL describe degraded or empty data states in user-facing language and MUST NOT expose raw backend, API, or fetch failure messages in visible UI.

#### Scenario: Cache fallback is active
- **WHEN** Research is rendered from tracked cache
- **THEN** the page states that verified cached paper data is being used
- **AND** it shows source or update context when available
- **AND** it does not show backend/API failure wording as the primary message

#### Scenario: AI summary request fails
- **WHEN** an on-demand AI paper summary cannot be generated
- **THEN** the detail drawer shows a localized unavailable message
- **AND** the user can retry
- **AND** raw errors such as `fetch failed` are not visible

### Requirement: Canonical public taxonomy
Research taxonomy SHALL merge equivalent public task and method refs before aggregation so users do not see duplicate concepts caused by prefixed or alias slugs.

#### Scenario: Equivalent task refs exist
- **WHEN** papers contain both `agent-task-completion` and `task-agent-task-completion`
- **THEN** the task list exposes one visible task item
- **AND** paper counts, detail routes, and filters use the canonical slug

### Requirement: Mobile-first paper access
The Research landing page SHALL prioritize the paper feed on mobile while keeping task and method navigation available as compact secondary controls.

#### Scenario: Mobile user opens Research
- **WHEN** the viewport is mobile sized
- **THEN** the paper feed appears before full taxonomy side panels
- **AND** task/method shortcuts render as compact chips or equivalent controls

### Requirement: Efficient paper feed controls
The Research paper feed SHALL provide clear primary actions and lightweight filters without inflating unavailable metrics.

#### Scenario: Paper lacks citation data
- **WHEN** a paper has no citation count
- **THEN** the paper card does not present `N/A` as a primary citation metric

#### Scenario: User filters by code availability
- **WHEN** the user enables the code filter
- **THEN** the feed and pagination only include public papers with verified code or implementation links

#### Scenario: PDF thumbnails are below the initial rows
- **WHEN** a paper appears below the first visible rows
- **THEN** the card may show a stable placeholder instead of immediately fetching a PDF thumbnail

#### Scenario: User triages a paper locally
- **WHEN** a user chooses reading list, compare, or read-later on a paper card
- **THEN** the card records that paper in a persisted local workspace list
- **AND** the action state is visible without inventing backend-synced user data

### Requirement: Research detail pages prioritize supporting papers
Task and method detail pages SHALL show matching papers before benchmark or relation panels so users first see the evidence behind the taxonomy item.

#### Scenario: User opens task detail
- **WHEN** a task detail page has matching papers and benchmarks
- **THEN** matching papers appear before benchmark panels in the main content order

### Requirement: Taxonomy source provenance
Task and method taxonomy cards SHALL show concise source provenance from verified paper refs, including paper count and latest update context when the visible paper list can provide it.

#### Scenario: Taxonomy card has matching public papers
- **WHEN** a task or method card is rendered from verified refs
- **THEN** the card states that verified refs were used
- **AND** it shows the real paper count
- **AND** it shows the latest paper update date when available
