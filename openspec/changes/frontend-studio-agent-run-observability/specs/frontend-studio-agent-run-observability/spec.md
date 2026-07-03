## ADDED Requirements

### Requirement: Studio overview summarizes agent runtime state
The web console SHALL expose `/studio` with runtime status, active/failed/completed run counts, artifact and quality summaries, source health preview, error summary, and latest runs that link to run detail pages.

#### Scenario: Overview loads with API or fallback data
- **WHEN** an operator opens `/studio`
- **THEN** the page displays runtime summary cards and latest agent runs without requiring backend-only observability fields.

### Requirement: Studio run list supports dense filtering
The web console SHALL expose `/studio/runs` with a dense run table containing run id, agent, profile, status, started time, duration, input/output counts, step count, artifact count, quality score, and error count.

#### Scenario: Operator filters runs
- **WHEN** an operator filters by keyword, agent, status, profile, date range, errors, quality score, or sort order
- **THEN** the visible run rows update client-side and an empty result displays `No agent runs found`.

### Requirement: Studio run detail provides observability evidence
The web console SHALL expose `/studio/runs/[runId]` with a run header, workflow DAG or mobile timeline, selected step detail, logs, tool calls, memory hits, artifacts, quality checks, and error traces.

#### Scenario: Operator inspects a failed step
- **WHEN** an operator opens a run detail page and selects a failed DAG node
- **THEN** the selected step detail is shown and the error trace can be inspected without crashing the page.

### Requirement: Studio uses HTTP API data with deterministic fallback
The Studio observability surface SHALL consume existing `/api/v1/runs*` endpoints server-side and merge deterministic mock observability data for missing DAG, tool, memory, quality, artifact preview, and error fields.

#### Scenario: API is unavailable
- **WHEN** API run requests fail or return partial data
- **THEN** Studio still renders fallback mock observability data and marks the page as partial or fallback rather than failing completely.
