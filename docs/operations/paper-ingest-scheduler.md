# Paper Ingest Scheduler

This document is retained as a deprecation notice. The old paper ingest scheduler, `news:queue:papers`, `add-paper-ingest`, paper reader backfill tasks, and `/api/v1/papers*` routes were retired during the Harness + Research cleanup.

Use the current backend surfaces instead:

```powershell
.\.venv\Scripts\python.exe -m interfaces.cli.news api serve --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe -m interfaces.cli.news workers status
.\.venv\Scripts\python.exe -m interfaces.cli.news sources health --json
.\.venv\Scripts\python.exe -m interfaces.cli.news api openapi --output docs/api/openapi.json
```

Research paper analysis is exposed through:

```text
POST /api/v1/research/papers/analyze
GET  /api/v1/research/papers/{paper_id}/analysis
GET  /api/v1/research/papers/{paper_id}/reader
POST /api/v1/research/papers/{paper_id}/ask
GET  /api/v1/research/runs/{run_id}/trace
```

Generic recurring work should use `news schedules` with real task types such as source health checks or memory reindexing. Do not recreate old paper ingest queues as compatibility adapters.
