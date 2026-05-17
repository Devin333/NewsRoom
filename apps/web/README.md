# NewsRoom Web Console

This is the first productized Web Console for NewsRoom. It uses Next.js, React,
TypeScript, and Tailwind CSS, and calls only the public NewsRoom HTTP API.

## Environment

```bash
NEWSROOM_API_BASE_URL=http://localhost:8000
NEWSROOM_API_TOKEN=
```

## Commands

```bash
npm install
npm run dev
npm run typecheck
npm run lint
npm run build
```

Repository-level file checks:

```bash
python -m scripts.dev web-check
```

## Pages

```text
/                   Dashboard
/runs               Runs list
/runs/[runId]       Run detail
/reports            Reports list
/reports/[reportId] Report detail
/sources            Source health
/workers            Worker and queue status
/memory             Memory search
/approvals          Approval list and decisions
/settings           API settings view
```

The first version is read-heavy. It includes controlled run operations and
approval decisions, each with explicit confirmation. It does not include a login
system, realtime logs, or report deletion/publish UI.
