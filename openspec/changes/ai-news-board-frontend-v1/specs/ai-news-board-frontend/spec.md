## ADDED Requirements

### Requirement: AI News Board front-stage page
The system SHALL render `/news` as a reader-facing AI News Board with an editorial hero, filter controls, facets, top story treatment, and a news stream.

#### Scenario: Board renders
- **WHEN** a signed-in Portal user opens `/news`
- **THEN** the page shows the AI News Board hero, source/topic coverage metadata, filter controls, and either a news stream or an explicit empty/degraded state
- **AND** the page does not present backend monitoring or dashboard table semantics as the primary experience

### Requirement: Real news data states
The AI News Board SHALL use backend or local artifact AI News output as runtime business data and MUST NOT invent bundled mock news when those sources are unavailable.

#### Scenario: No real news output
- **WHEN** backend and local AI News artifacts return no public news items
- **THEN** `/news` shows an explicit empty or degraded state
- **AND** the API response includes notices explaining that no real AI News output is available

### Requirement: PRD query aliases
The news list API and page SHALL accept PRD-style aliases for period, source, and sort while preserving existing URL behavior.

#### Scenario: PRD query aliases
- **WHEN** `/api/news?period=weekly&source=github&sort=trending` is requested
- **THEN** the request is handled like the equivalent existing date range, source type, and heat-score sort filters

### Requirement: News row and top story content
The AI News stream SHALL show source, published time, category, topic tags, and related paper/project/community counts for each news item.

#### Scenario: News stream item
- **WHEN** a news item has related paper, project, or community references
- **THEN** the row displays the corresponding counts and links to the detail view

### Requirement: News detail evidence and relations
The news detail page SHALL show source metadata, summary, evidence, and related papers/projects/community references, with clear empty states when relation data is missing.

#### Scenario: Missing relations
- **WHEN** a news item has no related papers, projects, or community references
- **THEN** the detail page shows a clear empty state for those relations and does not crash

### Requirement: AI News PRD alignment
The PRD-03 document SHALL reflect the implemented v1 behavior after completion.

#### Scenario: PRD status
- **WHEN** the AI News Board implementation is completed
- **THEN** PRD-03 status is marked as implemented/aligned and no longer describes runtime mock news as the MVP data source
