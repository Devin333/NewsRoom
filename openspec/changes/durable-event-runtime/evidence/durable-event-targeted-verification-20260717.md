# Durable Event Targeted Verification Evidence

Date: 2026-07-17

Verified commit: `b935d4fd5cd07bf7550fd955e4f0efaf72c0ab8d`

OpenSpec tasks: `10.1`, `10.2`, `10.3`

Status: PASSED for tasks 10.1-10.3. Tasks 9.5, 10.4, and 10.5 remain open.

## 10.1 Targeted suite

The suite ran from a detached clean worktree at the verified commit. It covered
framework event contracts and public errors, trace propagation, Harness,
Workflow runtime and checkpoints, manifests and inspection, SQLite/PostgreSQL
event adapters, migration, replay, rollback qualification, application
services, and API/CLI/MCP transport and operator surfaces.

Result:

```text
1425 passed, 69 skipped, 210 warnings in 118.28s
```

The 69 skips are explicit PostgreSQL opt-in groups, not disabled assertions:

| Environment gate | Count | Covered group |
| --- | ---: | --- |
| `NEWS_TEST_POSTGRES_DSN` | 30 | event-store PostgreSQL conformance 27; replay-checkpoint PostgreSQL conformance 3 |
| `NEWSROOM_RUN_POSTGRES_EVENT_INTEGRATION=1` | 39 | durable-event PostgreSQL integration 33; recorded-activity integration 5; replay-checkpoint integration 1 |

The warnings are existing FastAPI `on_event` deprecations. There were no test,
collection, architecture, or contract failures. The rollback-specific suite
contributed 23 passing adversarial tests, including independent signing roots,
semantic artifact binding, time and release binding, output race protection,
private-key ACLs, and atomic qualification publication.

The repository-required smoke gate also ran in an isolated worktree containing
only this committed batch:

```text
python -m scripts.dev smoke
1011 passed, 23 skipped, 12 warnings
sources validate: is_valid=true, error_count=0, warning_count=0
```

## 10.2 Real storage faults

The real-storage gate was executed separately from the opt-in targeted suite:

| Backend | Result | Evidence boundary |
| --- | ---: | --- |
| SQLite | 9 passed | real process-death, lock/read-only/full/corruption, backup/recovery, and single-host durability behavior |
| PostgreSQL | 33 passed | real concurrent transactions, same-stream sequence allocation, uncertain commit/crash recovery, rollback, delivery, and integrity behavior |

The PostgreSQL run used a dedicated test database and removed that database
after the suite. FakeConnection-only coverage was not used to qualify task
10.2. The committed fault cases are anchored by `22df65a2` and the durable
adapter/conformance history preceding this evidence.

## 10.3 Fixed SLO benchmark

Canonical evidence:
`durable-event-benchmark-qualification-20260717.json`

Canonical checksum:
`sha256:4667d8826ea252cec7020a975b60c23cfe1d08285b566dd60f9b8d31d842962f`

Strict verification:

```text
python -m scripts.durable_event_benchmark verify --evidence <qualification-json>
correctness: 8/8
qualification: 12/12
SLO: 12/12
```

| Workload | Committed | Rate | p95 | Correctness |
| --- | ---: | ---: | ---: | --- |
| SQLite, 1 writer / 1 stream | 15,000/15,000 | 25.001/s | 15.363 ms | 0 error/loss/duplicate/gap/checksum failure |
| PostgreSQL, 8 writers / same stream | 60,000/60,000 | 100.001/s | 2.768 ms | 0 error/loss/duplicate/gap/checksum failure |
| PostgreSQL, 8 writers / 8 streams | 60,000/60,000 | 100.001/s | 2.718 ms | 0 error/loss/duplicate/gap/checksum failure |

The 10,000-event ordered schema/checksum read completed in 2.788 seconds and
deterministic replay completed in 3.689 seconds. Payload, extension, backlog,
admission, lease-recovery, cleanup, machine, disk, Python, SQLite, psycopg, and
PostgreSQL configuration evidence is retained in `durable-event-benchmark.md`
and the canonical JSON. The benchmark implementation and evidence were
committed in `07841be7`.

## Rollback boundary

The committed rollback tool proves local invariants and rejects fabricated or
unbound external evidence, but no real deployment binary switch, PostgreSQL
rollback continuity run, external provider effect audit, traffic-control run,
or two-person production approval bundle has been supplied. Therefore local
rollback evidence remains `INCOMPLETE`, task 9.5 is not checked, and neither PRD
may be marked `IMPLEMENTED`.

## Disposition

- Task 10.1 is complete based on the 1,425-test targeted run.
- Task 10.2 remains complete based on the independent real SQLite/PostgreSQL runs.
- Task 10.3 is complete based on the strict fixed 600-second qualification.
- Task 10.4 remains open because the dirty main worktree cannot qualify the final all-repository gate.
- Task 10.5 remains open until every Definition of Done item, including task 9.5, is satisfied.
