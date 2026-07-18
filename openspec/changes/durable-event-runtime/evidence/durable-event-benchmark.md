# Durable Event Benchmark Evidence

Date: 2026-07-18

OpenSpec task: 10.3

Status: PASSED - OpenSpec task 10.3 qualification is complete.

## 2026-07-18 Exact-Candidate Refresh

The prior qualification record below is retained as historical evidence. The
following run was executed from the clean candidate that includes the memory
trace identity fix and PRD index synchronization:

```text
candidate_commit: 0a24e52b8f084099aa5f614c7a9c64081ce79ca3
candidate_tree:   9ef7b8720e6392845299849dbe1598f60e3d77f5
candidate_parent: 06b0b19eb7c0cd23a33cc98c9defaa449f3df68c
started_at:  2026-07-17T20:09:09.196284Z
finished_at: 2026-07-17T20:44:34.879743Z
```

Evidence:
`durable-event-benchmark-qualification-20260718.json`

Canonical evidence checksum:
`sha256:a4cfb53274e5b5dada07b3feeb6f3bc87fb13630a8a7cf760fdf8cce2dba66ae`

Strict verification:

```powershell
python -m scripts.durable_event_benchmark verify `
  --evidence openspec/changes/durable-event-runtime/evidence/durable-event-benchmark-qualification-20260718.json
```

The fixed 600-second workloads completed with zero errors:

| Workload | Committed | Rate | p50 | p95 | p99 |
| --- | ---: | ---: | ---: | ---: | ---: |
| SQLite, 1 writer / 1 stream | 15,000/15,000 | 25.001/s | 11.996 ms | 14.402 ms | 25.685 ms |
| PostgreSQL, 8 writers / same stream | 60,000/60,000 | 100.001/s | 2.803 ms | 3.423 ms | 3.754 ms |
| PostgreSQL, 8 writers / 8 streams | 60,000/60,000 | 100.001/s | 2.665 ms | 3.266 ms | 3.556 ms |

Read/replay processed 10,000 events with zero loss, duplicate, or checksum
failure (ordered read 4.580 s; deterministic replay 5.755 s). Committed
process recovery read every committed event. SQLite and PostgreSQL dispatcher
worker-death recovery completed in 5.859 s and 5.830 s respectively, below the
10-second two-lease bound. PostgreSQL cleanup removed 120,525 generated rows
across five exact scopes and left zero rows in all scoped tables.

All correctness (8/8), qualification (12/12), and SLO (12/12) gates passed.

## 2026-07-18 Final Candidate Qualification

The fixed workload was rerun after the replay reducer audit fix. The benchmark
JSON is retained at
`durable-event-benchmark-qualification-20260718-a2662442.json` and strict
verification passed.

```text
candidate_commit: a266244246b33c093905562cb9e3a514ea82703f
candidate_tree:   140ff053f87a096a89877e044c8f527439905ca0
started_at:       2026-07-18T07:02:14.150393Z
finished_at:      2026-07-18T07:36:42.349180Z
evidence_checksum: sha256:7485553ad9a4ceff2bab6194e4baa48b5259b2be5af27931933daf64e3cd11e0
file_sha256:       sha256:25f775da88312cf1545dfae571f20953812385f820c723e2a4c6930a751e4790
```

The benchmark executed from a descendant commit whose production scope
(`business`, `framework`, `infrastructure`, `interfaces`, `scripts`) is byte-
identical to the candidate; the source binding is recorded in
`durable-event-benchmark-source-binding-20260718-a2662442.json`.

| Workload | Committed | Rate | p50 | p95 | p99 |
| --- | ---: | ---: | ---: | ---: | ---: |
| SQLite, 1 writer / 1 stream | 15,000/15,000 | 25.001/s | 10.868 ms | 15.462 ms | 24.912 ms |
| PostgreSQL, 8 writers / same stream | 60,000/60,000 | 100.001/s | 1.947 ms | 2.834 ms | 3.195 ms |
| PostgreSQL, 8 writers / 8 streams | 60,000/60,000 | 100.001/s | 1.962 ms | 2.743 ms | 3.133 ms |

The 10,000-event ordered read/replay completed with zero loss, duplicate, or
checksum failure (read 3.071 s, replay 3.914 s). PostgreSQL cleanup reported
zero rows in every generated scope. All correctness, qualification, and SLO
gates passed. This remains technical benchmark evidence only and does not
provide governance activation or release qualification.

## Benchmark boundary

- All workload publication enters `EventRuntime.publish(EventPublishRequest)`.
  The benchmark does not construct `EventCandidate` or call a store append API
  directly.
- Commit-append, delivery, backlog admission, committed-process recovery, and
  dispatcher worker-death recovery are separate workloads. This prevents
  SQLite dispatcher lock contention from being mislabeled as commit-append
  latency while still exercising real event/outbox and delivery paths.
- A qualification run requires exactly 600 seconds, 10,000 read/replay events,
  and both PostgreSQL stream modes. Short or partial runs are emitted only as
  `smoke_passed` and `verify` rejects them unless `--allow-smoke` is explicit.
- Every PostgreSQL run registers five random exact cleanup scopes: same-stream
  append, multiple-stream append, delivery, backlog, and lease recovery.
  Cleanup uses exact tenant, subscription, and stream equality/`ANY` predicates,
  never a prefix or `LIKE`, and verifies zero rows across 14 related tables.

## Fixed 600-second qualification

Evidence:
`durable-event-benchmark-qualification-20260717.json`

Canonical evidence checksum:
`sha256:4667d8826ea252cec7020a975b60c23cfe1d08285b566dd60f9b8d31d842962f`

Strict verification command:

```powershell
python -m scripts.durable_event_benchmark verify `
  --evidence openspec/changes/durable-event-runtime/evidence/durable-event-benchmark-qualification-20260717.json
```

| Workload | Result | Rate | p50 | p95 | p99 |
| --- | ---: | ---: | ---: | ---: | ---: |
| SQLite, 1 writer / 1 stream | 15,000/15,000, 0 errors | 25.001/s | 10.485 ms | 15.363 ms | 37.825 ms |
| PostgreSQL, 8 writers / same stream | 60,000/60,000, 0 errors | 100.001/s | 1.977 ms | 2.768 ms | 3.130 ms |
| PostgreSQL, 8 writers / 8 streams | 60,000/60,000, 0 errors | 100.001/s | 1.973 ms | 2.718 ms | 3.069 ms |

All three fixed workloads ran for 600 seconds and sustained their target rate.
They recorded zero append error, event loss, duplicate sequence, sequence gap,
and checksum failure. Cross-process recovery read 100 percent of committed
events. Average canonical event size remained within five percent of 4 KiB.

The 10,000-event ordered schema/checksum read completed in 2.788 seconds and
deterministic replay completed in 3.689 seconds, with zero loss, duplicate, or
checksum failure. The strict verifier passed correctness 8/8, qualification
12/12, and SLO 12/12.

## Optimized stable 30-second smoke

Command shape (DSN was injected from the local environment and is not recorded):

```powershell
python -m scripts.durable_event_benchmark run `
  --workspace .tmp/durable-event-pool-smoke-30s-20260717 `
  --duration-seconds 30 `
  --read-replay-events 100 `
  --smoke `
  --evidence openspec/changes/durable-event-runtime/evidence/durable-event-benchmark-pool-30s-20260717.json
```

Evidence checksum:
`sha256:b995db4356921321e505fdd72e82e07728db0bf38af22156a82f05d05cd84f8b`

| Workload | Result | Rate | p50 | p95 | p99 | Target assessment |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| SQLite, 1 writer / 1 stream | 750/750, 0 errors | 25.024/s | 10.426 ms | 14.776 ms | 25.809 ms | smoke p95/p99 pass |
| PostgreSQL, 8 writers / same stream | 3,000/3,000, 0 errors | 100.022/s | 1.995 ms | 2.843 ms | 3.441 ms | smoke p95/p99 pass |
| PostgreSQL, 8 writers / 8 streams | 3,000/3,000, 0 errors | 100.024/s | 2.015 ms | 2.841 ms | 3.474 ms | smoke p95/p99 pass |

All three append workloads had zero loss, duplicate sequence, sequence gap,
and checksum/schema failure. Average canonical event size was 4,099-4,101
bytes, within five percent of the 4 KiB target. A restarted child process read
and verified 100 percent of committed events.

The earlier stable sample measured PostgreSQL p95 near 144 ms because every
publish opened and closed a physical connection. The production adapter now
shares a bounded `psycopg_pool.ConnectionPool` by normalized DSN/configuration
while preserving one transaction per publish and the existing UoW close
semantics. The benchmark explicitly releases every writer/probe store. This
reduced both PostgreSQL p95 values below 3 ms without changing durability,
schema, security, cleanup, or correctness gates. The fixed qualification above
subsequently confirmed the result over the required 10-minute window.

## Delivery, limits, and recovery

- SQLite delivery: 100/100 ACK, 0 duplicate calls, 0 pending, 0 checkpoint
  mismatch, 79.399 events/s dispatch throughput.
- PostgreSQL delivery: 100/100 ACK, 0 duplicate calls, 0 pending, 0 checkpoint
  mismatch, 437.007 events/s dispatch throughput.
- Worker-death recovery used a real child process that claimed a five-second
  lease and exited with `os._exit(91)`. SQLite reclaimed and ACKed in 5.896
  seconds; PostgreSQL reclaimed and ACKed in 5.918 seconds. Both are below the
  `2 * lease_duration` limit of 10 seconds.
- Inline payload above 64 KiB, more than 32 extensions, and extensions above
  8 KiB were rejected before append.
- Exact pending warning/hard-limit probes passed on SQLite and PostgreSQL; the
  rejected event did not allocate a sequence or durable row.
- PostgreSQL cleanup removed 120,525 rows from the five generated scopes and
  verified a total of zero remaining rows across every scoped table. It did not
  touch rows from earlier benchmark processes.

## Machine and configuration

```text
OS: Windows 10.0.19045 SP0 / NTFS
CPU: Intel Core i7-14700KF, 20 cores / 28 logical CPUs
RAM: 34,134,794,240 bytes
Disk: Samsung SSD 970 EVO Plus 2TB, NVMe SSD
Python: 3.14.4
SQLite: 3.50.4, WAL, synchronous=FULL, busy_timeout=5000 ms,
        page_size=4096, wal_autocheckpoint=1000
psycopg: 3.3.4
PostgreSQL: 18.3, synchronous_commit=on, fsync=on,
            full_page_writes=on, shared_buffers=128MB
```

## Verification

```text
benchmark + architecture tests: 10 passed
python -m scripts.dev compile: passed
benchmark evidence verify --allow-smoke: passed
qualification evidence strict verify: passed
git diff --check (scoped files): passed
```

## Qualification disposition

The fixed run used the isolated PostgreSQL database
`newsroom_event_benchmark_20260717`; its five exact scopes removed 120,525 rows
and left zero residual rows across all 14 related tables. Machine, SQLite, and
PostgreSQL configuration evidence is retained in the qualification JSON.

This evidence completes OpenSpec task 10.3 only. It does not satisfy the real
deployment rollback qualification in task 9.5 or the final repository gates in
tasks 10.4 and 10.5. Both PRDs therefore remain `IN_PROGRESS`.
