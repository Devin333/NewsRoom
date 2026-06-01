## Why

Research Reader can currently show "document not ready" for published papers that predate the visual compiler rollout. New ingest already enqueues single-paper compilation, but there is no runtime task that scans all real published papers and backfills missing or stale Reader artifacts. Operators also need a clear Studio action to start that runtime work.

Reader tables must remain reader-native structured content. A compiled table should carry a table model, table HTML asset, style metadata, and deterministic validation instead of relying on screenshots or blank visual placeholders.

## What Changes

- Add a Paper Reader visual compile backfill runtime task that scans the real published paper cache and enqueues `papers.visual_compile` for papers whose compiled artifact is missing, not published, failed, or missing source-comparison proof.
- Expose backend and frontend ops endpoints for triggering the backfill task, preserving existing paper read and single-paper compile APIs.
- Add a periodic schedule helper for the same backfill task so local and deployed runtimes can continuously close gaps after ingest, migrations, or compiler upgrades.
- Surface the action in Studio Paper Reader Operations with localized copy and queue feedback.
- Strengthen structured table expectations: table assets and blocks must carry `tableModel`/`tableHtml`; tests cover row/cell colors, booktabs rules, `cmidrule`, `multicolumn`, and `multirow`.

## Impact

- Affects paper visual compiler service, paper worker handlers, worker/schedule services, paper API routes, Studio BFF routes, and Studio ops UI.
- Existing `/api/v1/papers`, paper document reads, and single-paper compile routes remain compatible.
- Backfill scans only real published papers from the paper cache/artifact path and does not fabricate Reader content.
