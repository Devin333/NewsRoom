# TypeScript SDK Contract

The TypeScript SDK should call the same `/api/v1` HTTP contract as `NewsClient`.

Minimum surface:

- `client.runs.createDaily({ topic, profile, sourceLimit })`
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
- `client.approvals.resumeWorkflow(approvalId, { workflowId, profile, runId, decisionKey, checkpointStorePath })`

SDK implementations must preserve the common `ApiResponse` / `ApiError` envelope and must not read runtime storage directly.
Run inspection helpers must call `/api/v1/runs/...` endpoints and must not read `.newsroom/runs` directly.
Approval workflow resume helpers must call `POST /api/v1/approvals/{approvalId}/resume-workflow` and must not resolve checkpoints locally.
