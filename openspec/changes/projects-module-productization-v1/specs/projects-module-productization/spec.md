## ADDED Requirements

### Requirement: Projects product API
The system SHALL expose `/api/v1/projects/*` product endpoints through `ProjectApplicationService`.

#### Scenario: Projects home
- **WHEN** `GET /api/v1/projects` is requested
- **THEN** the response uses the standard API envelope
- **AND** includes hot, rising, tool, case, collection, watchlist, and recommendation sections

### Requirement: Real project data source
The Projects module SHALL derive project entities from real Project Radar backend or local artifacts and MUST NOT substitute bundled fake projects when real project data is missing.

#### Scenario: Missing real project data
- **WHEN** no Project Radar backend or local artifact payload exists
- **THEN** project lists return empty items with notices
- **AND** no synthetic runtime business projects are added

### Requirement: Hot and Rising rankings
The Projects module SHALL provide distinct Hot and Rising rankings with explanatory reasons.

#### Scenario: Ranking request
- **WHEN** `/api/v1/projects/hot` or `/api/v1/projects/rising` is requested
- **THEN** each returned item includes rank, score, and a human-readable reason based on real metrics or derived signals

### Requirement: Tools and Cases
The Projects module SHALL expose tool search/comparison/recommendation and module case search/detail APIs.

#### Scenario: Tool and case queries
- **WHEN** a tool or case endpoint is requested
- **THEN** the response is built from real project/capability/case data where available
- **AND** empty states are explicit when no matching real-derived data exists

### Requirement: Lab sessions
The Projects module SHALL create and update Lab sessions from user design problems.

#### Scenario: Start Lab session
- **WHEN** a user posts a design problem
- **THEN** the service returns a Lab session with a requirement profile, graph state, at least one generated question, and similar cases when available

### Requirement: Watchlist and interactions
The Projects module SHALL persist watchlist items and user interaction events for later evolution analysis.

#### Scenario: User records behavior
- **WHEN** a watchlist or interaction endpoint is called
- **THEN** the event is persisted in Projects state
- **AND** it can be read by the application service without requiring a workflow run

### Requirement: Frontend Projects routes
The frontend SHALL provide `/projects` product home and module pages for hot, rising, tools, cases, lab, collections, and watchlist while preserving existing detail/Project Radar compatibility.

#### Scenario: Projects navigation
- **WHEN** a user opens any `/projects/*` module page
- **THEN** the page renders the corresponding Projects experience, calls the Projects API client, and shows empty/degraded states for missing real data
