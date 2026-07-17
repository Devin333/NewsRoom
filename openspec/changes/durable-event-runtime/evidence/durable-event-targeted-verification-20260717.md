# Durable Event Targeted Verification Evidence

Date: 2026-07-17

Tasks 10.1-10.3 verified commit: `b935d4fd5cd07bf7550fd955e4f0efaf72c0ab8d`

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

The committed rollback tool still keeps local evidence `INCOMPLETE`, but a real
approval-pending staging run has now completed for the frozen runtime candidate
`fbdec37a0afd6b08796818ccd6cb7fea2e401f93` against rollback release
`570f840c7df3870841c93e37480d7a53a67921dd`.

Canonical local evidence:
`.newsroom/durable-event-rollback-local-fbdec37a-final/rollback-evidence.json`

Local `evidence_checksum`:
`sha256:aaba41c71b5527413d2079e59a1785f03443a3cea599a5b24f18f66d3319d77d`

Canonical technical evidence:
`rollback-staging-fbdec37a-awaiting-approval/technical/technical-evidence.json`

Technical `evidence_checksum`:
`sha256:b73f2901d0a72a3556ed5a2ac17d0b8ba8a5d8e54ec65e83d356939c166f6eda`

Approval request `request_checksum`:
`sha256:e1fe45af7d9220e55de015770ba719b340c4f209792a55ce6d9bac742da6201c`

The run used a newly created isolated PostgreSQL database, clean detached
candidate and rollback worktrees, different actual worker processes, a real
process exit after the external-effect transaction, a five-second lease
recovery, durable dispatcher pause, and direct controller queries. It proved:

| Boundary | Result |
| --- | --- |
| Accepted prefix | 20 complete canonical events preserved byte-for-byte; next accepted sequence 21 |
| Concurrent writers | 0 duplicate sequence; contiguous stream watermark |
| Preserved ledgers | delivery 2, inbox 1, checkpoint 1, dead letter 1; counts and checksums unchanged |
| External effect | 2 invocations, 1 applied effect, stable result checksum |
| Negative gates | unknown schema, forbidden payload, identity collision, and record-checksum tamper rejected without watermark advance |
| Cross-release projection | candidate and rollback exact JSONL checksum `sha256:d53e489a40c1dd4cb5168be3b9ad9ec5b786ed9fa3283795504bd67beceec8ac` |
| Canonical projection rows | checksum `sha256:3cf63e515b45b8b4af1e3ac21fabe635303d164d44a20fc67ec0ecdeb6390704` |

The earlier opt-in PostgreSQL regression remains retained, and the current
candidate staging CLI completed independently in 26.3 seconds:

```text
NEWSROOM_RUN_ROLLBACK_STAGING_INTEGRATION=1
9 passed in 28.81s

python -m scripts.durable_event_rollback_staging run ...
status=awaiting_approval
```

Task 9.5 remains unchecked because the technical bundle is intentionally
`awaiting_approval`. A real approval system must provide separated operator and
approver identities plus an Ed25519 signature over the exact approval record.
An independent deployment attester and release qualifier must then execute
`attest-external`, `qualify`, and strict `verify` with three distinct trust
roots. PRD 19A also requires a real bounded deployment observation of the
pre-deletion compatibility candidate `42a8636cd72aea0c466126fc5f2d69c55db1a1d6`
and external-consumer sign-off before the deletion release can be qualified.
Repository tests and the approval-pending rollback bundle satisfy neither
external requirement. Until both chains exist, neither PRD may be marked
`IMPLEMENTED`.

## Disposition

- Task 10.1 is complete based on the 1,425-test targeted run.
- Task 10.2 remains complete based on the independent real SQLite/PostgreSQL runs.
- Task 10.3 is complete based on the strict fixed 600-second qualification.
- Task 10.4 remains open until task 9.5 and the compatibility observation are
  complete; the final all-repository gate must then pass before task 10.5
  updates the PRDs and final evidence.
- Task 10.5 remains open until every Definition of Done item, including task 9.5, is satisfied.
