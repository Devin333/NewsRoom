## ADDED Requirements

### Requirement: Public Portal homepage
The Portal surface SHALL render a public reader-facing homepage at `/` and MUST NOT render the legacy dashboard home at that route.

#### Scenario: Anonymous Portal root visit
- **WHEN** an anonymous user opens `/` in Portal mode
- **THEN** the frontend renders the Portal homepage without redirecting to `/login`
- **AND** the page does not include legacy dashboard or Studio shell content

#### Scenario: Admin root visit
- **WHEN** an anonymous user opens `/` in Admin mode
- **THEN** middleware redirects the user to `/login` with `next=/`

### Requirement: Portal module entries
The Portal homepage SHALL show module entries for AI News, Project Radar, Paper Radar, Community Pulse, Cross-board Evidence Graph, and Reports / Briefings.

#### Scenario: Homepage modules render
- **WHEN** the Portal homepage loads
- **THEN** the user can see links to `/news`, `/tech/repos`, `/papers`, `/community`, `/topics?view=evidence-graph`, and `/reports`

### Requirement: Real homepage data summaries
The Portal homepage SHALL derive module counts and highlights from existing NewsRoom data loaders and MUST NOT invent business data when a source is unavailable.

#### Scenario: Data source unavailable
- **WHEN** one homepage data source fails or returns no items
- **THEN** the affected module shows an explicit degraded or empty state
- **AND** the rest of the homepage remains usable

### Requirement: Portal navigation convergence
The Portal navigation SHALL keep Papers, Today, Trends, and Reports as primary groups, with Papers limited to Trending Papers, Tasks, and Methods.

#### Scenario: Papers navigation opens
- **WHEN** the Portal navigation renders the Papers group
- **THEN** the child links are Trending Papers, Tasks, and Methods
- **AND** the group does not show Benchmarks, Papers with Code, Reading List, or Paper Digests as child links

#### Scenario: Community navigation opens
- **WHEN** the Portal navigation renders the Today group
- **THEN** Community Buzz links to `/community`

### Requirement: Evidence graph MVP view
The Topics surface SHALL render a structured Cross-board Evidence Graph view when `view=evidence-graph` is selected.

#### Scenario: Evidence graph route opens
- **WHEN** a user opens `/topics?view=evidence-graph`
- **THEN** the page shows a Cross-board Evidence Graph view with Paper, Project, News, and Community evidence sections
- **AND** the page provides an empty or degraded state without crashing when data is incomplete

### Requirement: Legacy dashboard homepage removal
The frontend SHALL remove the old dashboard homepage chain from Portal root routing and MUST NOT leave `/` dependent on dashboard components, dashboard data hooks, or dashboard BFF routes.

#### Scenario: Dashboard reference search
- **WHEN** the codebase is searched for `DashboardHomePage`
- **THEN** no `/` route imports or renders it
