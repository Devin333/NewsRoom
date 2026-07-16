# Migration Backfill And Shadow Evidence

Date: 2026-07-16

OpenSpec tasks: 9.1 and 9.2

## Implemented contracts

- `EventMigrationDryRun.map_record()` exposes the exact deterministic canonical
  mapping used by dry-run and backfill, including legacy 0-based offset and
  canonical source sequence metadata.
- `EventMigrationBackfill` imports only into an explicit staging
  `EventStorePort`. It appends an already validated and security-projected
  candidate in one unit of work and rejects any staging subscription that
  would materialize delivery work, so the migration cannot double-dispatch.
- Backfill progress is persisted after every source record in a versioned,
  checksummed JSON report using process/thread locking, file `fsync`, atomic
  replace, and directory `fsync`. Resume verifies source fingerprints,
  per-record mappings, and every previously imported staging event.
- Import reports distinguish imported, duplicate, checkpoint-mapped, and
  quarantined records. They preserve source location, legacy offset, source
  sequence, canonical sequence, content checksum, and record checksum without
  copying source payloads into diagnostics.
- Shadow comparison has only an `EventReaderPort` dependency. It verifies
  stream high watermark, event count/order, content checksum, canonical
  sequence, record checksum, and unresolved quarantine, and never publishes or
  invokes a dispatcher.
- CLI commands `events migration-backfill` and
  `events migration-shadow-compare` require an isolated staging root, produce
  checksum-protected reports, and leave legacy files and PostgreSQL rows
  unchanged.

## Fault And Boundary Coverage

- Empty source, first/last legacy offsets, duplicate identity, checkpoint
  mapping, invalid JSON quarantine, process-style interruption/resume, source
  mutation, missing staging progress, report checksum tampering, and failed
  atomic replace are covered against a real SQLite staging database.
- A real PostgreSQL integration fixture creates a legacy `workflow_events`
  source in an isolated schema, reads it using a repeatable-read/read-only
  transaction, imports it into SQLite staging, verifies offset `0/1` maps to
  sequence `1/2`, runs shadow compare, and confirms the source rows are
  unchanged.

## Verification Results

```text
migration targeted suites: 49 passed
real PostgreSQL legacy-source backfill: 1 passed
isolated staged smoke: 1006 passed, 23 skipped
git diff --check (scoped files): passed
```

The canonical Workflow/Harness writer cutover and removal of post-run indexing
were completed earlier in tasks 5.2-5.4. This phase adds only staging import and
read-only comparison; it does not introduce a second live writer or dispatcher.
