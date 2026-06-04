# Paper Ingest Scheduler

NewsRoom can run the Trending Papers pipeline through the standard scheduler and worker queue.

## Runtime Processes

Run these long-lived processes from the repository root:

```powershell
.\.venv\Scripts\python.exe -m interfaces.cli.news api serve --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe -m interfaces.cli.news worker run --worker-id paper-worker-1 --queue-name news:queue:papers --reclaim-stale-ms 600000
.\.venv\Scripts\python.exe -m interfaces.cli.news schedules run --tick-interval-seconds 60
```

Run the frontend from `frontend/`:

```powershell
$env:NEWSROOM_API_BASE_URL = "http://127.0.0.1:8000"
npm run dev -- -p 3001
```

## Schedules

Create or update the recurring paper ingest schedule:

```powershell
.\.venv\Scripts\python.exe -m interfaces.cli.news schedules add-paper-ingest --interval-seconds 21600 --candidate-limit 100 --min-github-stars 50
```

Create or update the visual compile backfill schedule:

```powershell
.\.venv\Scripts\python.exe -m interfaces.cli.news schedules add-paper-reader-backfill --interval-seconds 21600 --limit 50
```

Trigger a schedule immediately:

```powershell
.\.venv\Scripts\python.exe -m interfaces.cli.news schedules trigger papers-ingest-github-arxiv-daily
```

## Health Checks

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/workers"
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/queues?queue_name=news:queue:papers"
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/papers/ops/ingest?limit=10"
```
