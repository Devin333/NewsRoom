# TypeScript SDK Contract

The TypeScript SDK should call the same `/api/v1` HTTP contract as `NewsClient`.

Minimum surface:

- `client.research.analyzePaper({ paperId, sourceUrl, pdfUrl, runId, userId, metadata, options })`
- `client.research.analysis(paperId)`
- `client.research.reader(paperId)`
- `client.research.ask(paperId, { question, locale, selection, options })`
- `client.research.trace(runId)`
- `client.runs.get(runId)`
- `client.runs.list({ limit })`
- `client.runs.manifest(runId)`
- `client.runs.events(runId, { limit })`
- `client.runs.replay(runId)`
- `client.runs.diagnostics(runId)`
- `client.runs.health(runId)`
- `client.runs.catalogHealth()`
- `client.runs.compare({ baseRunId, targetRunId })`
- `client.runs.lineage(runId)`
- `client.runs.lineageUpstream(runId, { targetType, targetId })`
- `client.runs.lineageDownstream(runId, { sourceType, sourceId })`
- `client.runs.artifacts(runId)`
- `client.runs.artifact(runId, artifactKey)`
- `client.reports.latest()`
- `client.reports.list({ limit, workflowId })`
- `client.reports.get(reportId)`
- `client.reports.markdown(reportId)`
- `client.reports.quality(reportId)`
- `client.reports.search({ query, limit })`
- `client.memory.search({ query, collection, filters, limit })`
- `client.memory.get(documentId, { collection })`
- `client.memory.reindex(runId, { topic })`
- `client.mcp.catalog()`
- `client.mcp.capabilities()`
- `client.workers.list({ staleAfterSeconds })`
- `client.workers.get(workerId, { staleAfterSeconds })`
- `client.workers.queues({ queueNames })`
- `client.storage.metrics()`
- `client.storage.retentionPlan({ runId, now, reportRetentionDays })`
- `client.sources.list({ includeDisabled })`
- `client.sources.health({ includeDisabled })`
- `client.sources.validation()`
- `client.sources.get(sourceId)`
- `client.sources.probe(sourceId, { force, includeDisabled, limit })`
- `client.sources.fetchArxiv({ query, limit })`
- `client.sources.fetchGithubReleases({ repository, limit })`
- `client.schedules.list({ includeDisabled })`
- `client.schedules.createPaperIngest({ scheduleId, name, triggerType, intervalSeconds, runAt, candidateLimit, minGithubStars, queueName })`
- `client.schedules.trigger(scheduleId, { now })`
- `client.approvals.list({ status })`
- `client.approvals.get(approvalId)`
- `client.approvals.approve(approvalId, { decidedBy, reason })`
- `client.approvals.reject(approvalId, { decidedBy, reason })`
- `client.approvals.resumeContext(approvalId, { decisionKey })`

SDK implementations must preserve the common `ApiResponse` / `ApiError` envelope and must not read runtime storage directly.
Research helpers must call `/api/v1/research/...` endpoints and must not call retired `/api/v1/papers*` routes.
Run inspection helpers must call `/api/v1/runs/...` endpoints and must not read `.newsroom/runs` directly.
Approval resume helpers are context-only and must call `POST /api/v1/approvals/{approvalId}/resume-context`; workflow routing remains Harness-controlled.
