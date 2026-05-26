## ADDED Requirements

### Requirement: Project Radar Board front-stage page
The system SHALL render `/tech/repos` as a reader-facing Project Radar Board with an editorial hero, PRD-aligned filter controls, facets, trending project treatment, optional real clusters, and a project stream.

#### Scenario: Board renders
- **WHEN** a signed-in Portal user opens `/tech/repos`
- **THEN** the page shows the Project Radar hero, source/data-state metadata, filter controls, facets, and either project results or an explicit empty/degraded state
- **AND** the page does not present backend monitoring or dashboard table semantics as the primary experience

### Requirement: Real project data states
The Project Radar Board SHALL use backend or local artifact Project Radar output as runtime business data and MUST NOT invent bundled mock projects when those sources are unavailable.

#### Scenario: No real project output
- **WHEN** backend and local Project Radar artifacts return no public GitHub projects
- **THEN** `/tech/repos` shows an explicit empty or degraded state
- **AND** the API response includes notices explaining that no real Project Radar output is available

### Requirement: PRD project query aliases
The project list API and page SHALL accept PRD-style aliases while preserving existing URL compatibility.

#### Scenario: PRD query aliases
- **WHEN** `/api/projects?period=weekly&topic=rag&maturity=rising&sort=activity&limit=12` is requested
- **THEN** the request is handled by the Project Radar data source using equivalent normalized filters and pagination

### Requirement: Project row and trending content
The Project Radar stream SHALL show repo name, owner, description, language, stars, star delta, updated time, topics, maturity state, and related paper/news/community counts for each project when those fields exist.

#### Scenario: Project stream item
- **WHEN** a project has real related paper, news, or community references
- **THEN** the row displays the corresponding counts and links to the detail experience

### Requirement: Project detail drawer and shareable detail
The Project Radar Board SHALL support a detail drawer on `/tech/repos?project=<slug>` and keep `/projects/[slug]` as a shareable detail page using the same detail content.

#### Scenario: Missing relations
- **WHEN** a project has no related papers, news, or community references
- **THEN** the drawer and detail page show clear empty states for those relations and do not crash

### Requirement: Project Radar PRD alignment
The PRD-04 document SHALL reflect the implemented v1 behavior after completion.

#### Scenario: PRD status
- **WHEN** the Project Radar Board implementation is completed
- **THEN** PRD-04 status is marked as implemented/aligned and no longer describes runtime mock project data as the MVP data source
