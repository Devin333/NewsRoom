## ADDED Requirements

### Requirement: Paper Radar routes
The frontend SHALL render reader-facing Paper Radar pages at `/papers`, `/papers/tasks`, and `/papers/methods`.

#### Scenario: Trending papers opens
- **WHEN** a user opens `/papers`
- **THEN** the page shows an editorial Paper Radar board with hero, period controls, search, sort, domain sidebar, paper stream, and paper detail drawer support

#### Scenario: Task and method boards open
- **WHEN** a user opens `/papers/tasks` or `/papers/methods`
- **THEN** the page shows a reader-facing task or method board
- **AND** the page does not present backend monitoring, workflow, or admin dashboard semantics

### Requirement: Real paper data fallback
The Paper Radar runtime SHALL use real backend, tracked cache, or artifact paper data and MUST NOT use bundled catalog papers as public stream fallback.

#### Scenario: Backend unavailable with cached papers
- **WHEN** the backend paper API is unavailable and tracked cache or artifact papers exist
- **THEN** `/papers` and `/api/papers` render or return those real papers with degraded source state

#### Scenario: No real papers available
- **WHEN** backend, cache, and artifact paper data are unavailable
- **THEN** Paper Radar pages show an explicit empty or degraded state
- **AND** no bundled catalog paper is displayed as if it were current business data

### Requirement: PRD filter compatibility
The `/api/papers` BFF SHALL support PRD-05 list query parameters.

#### Scenario: Paper list query
- **WHEN** `/api/papers` is requested with `q`, `period`, `sort`, `task`, `method`, `limit`, or `offset`
- **THEN** the response applies those filters and ordering to the available real paper data
- **AND** the response keeps the existing success/error envelope shape

### Requirement: Task and method board enrichment
Task and method boards SHALL show real paper-derived counts and related content while allowing local taxonomy fallback.

#### Scenario: Task API unavailable
- **WHEN** the backend task API is unavailable
- **THEN** `/papers/tasks` may use local task taxonomy labels
- **AND** paper counts and latest papers are derived from real papers or shown as empty

#### Scenario: Method API unavailable
- **WHEN** the backend method API is unavailable
- **THEN** `/papers/methods` may use local method taxonomy labels
- **AND** representative papers and implementation counts are derived from real papers or shown as empty

### Requirement: Paper detail related states
The paper detail drawer SHALL expose related implementation, benchmark, project, news, community, and evidence sections.

#### Scenario: Related data exists
- **WHEN** a paper has related implementation, benchmark, project, news, community, or evidence fields
- **THEN** the drawer displays the related items with their real source links or metadata

#### Scenario: Related data missing
- **WHEN** related fields are empty
- **THEN** the drawer displays clear empty states
- **AND** the drawer does not fabricate related entities

### Requirement: Homepage Paper Radar entries
The Portal homepage SHALL include Paper Radar and the three research entries required by PRD-05.

#### Scenario: Homepage research entries render
- **WHEN** a user opens `/`
- **THEN** the homepage links to `/papers`, `/papers/tasks`, and `/papers/methods`
- **AND** latest paper highlights link to `/papers?paper=:id` when real papers are available

### Requirement: Papers navigation convergence
The Portal navigation SHALL keep Papers children limited to Trending Papers, Tasks, and Methods.

#### Scenario: Papers navigation children
- **WHEN** the Papers navigation group renders
- **THEN** its children are Trending Papers, Tasks, and Methods
- **AND** it does not show Benchmarks, Papers with Code, Reading List, or Paper Digests as children
