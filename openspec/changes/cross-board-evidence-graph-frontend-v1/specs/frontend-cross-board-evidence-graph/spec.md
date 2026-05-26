## ADDED Requirements

### Requirement: Evidence graph route
The Portal Topics surface SHALL render a Cross-board Evidence Graph page when `view=evidence-graph` is selected.

#### Scenario: Evidence graph route opens
- **WHEN** a user opens `/topics?view=evidence-graph`
- **THEN** the page shows a Cross-board Evidence Graph experience with topic search, graph summary, evidence sections, timeline, inspector, and related reports
- **AND** the page does not crash when graph data is empty or degraded

### Requirement: Evidence graph API
The frontend SHALL expose BFF APIs for graph search, node detail, and topic timeline.

#### Scenario: Fetch topic graph
- **WHEN** a user requests `GET /api/evidence-graph`
- **THEN** the response data includes `summary`, `nodes`, `edges`, `timeline`, and `relatedReports`
- **AND** supported query parameters include `topic`, `entity`, `period`, `nodeTypes`, `depth`, and `limit`

#### Scenario: Fetch node detail
- **WHEN** a user requests `GET /api/evidence-graph/nodes/:id` for an existing node
- **THEN** the response data includes the node, incoming edges, outgoing edges, and related nodes

#### Scenario: Fetch topic timeline
- **WHEN** a user requests `GET /api/topics/:topicId/timeline`
- **THEN** the response data includes topic timeline items derived from the evidence graph data

### Requirement: Real data graph assembly
The evidence graph SHALL derive runtime content from existing NewsRoom data loaders and MUST NOT invent bundled business data when sources are unavailable.

#### Scenario: Runtime data available
- **WHEN** paper, project, news, community, or report data is available
- **THEN** the graph includes matching evidence nodes and explainable edges for the selected topic

#### Scenario: Runtime data unavailable
- **WHEN** one or more data sources are empty or degraded
- **THEN** the graph returns the available sources plus notices for unavailable sources
- **AND** empty boards are represented as empty UI states rather than fake evidence

### Requirement: Evidence scoring
The evidence graph SHALL calculate topic evidence, trend, and confidence scores using deterministic PRD-aligned formulas.

#### Scenario: Summary scores render
- **WHEN** a graph response includes evidence nodes
- **THEN** the summary exposes `trendScore`, `evidenceScore`, and `confidenceScore`
- **AND** signal mix counts include papers, projects, news, and community signals

### Requirement: Homepage entry
The Portal homepage SHALL keep the Cross-board Evidence Graph module card linked to `/topics?view=evidence-graph`.

#### Scenario: Homepage evidence module
- **WHEN** the Portal homepage renders
- **THEN** the user can see the `Cross-board Evidence Graph` module entry
- **AND** its description is `把 Paper、Project、Community、AI News 串成证据链和技术演进链。`
