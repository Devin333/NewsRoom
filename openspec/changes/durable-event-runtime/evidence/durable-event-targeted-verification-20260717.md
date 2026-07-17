# Durable Event Targeted Verification Evidence

Date: 2026-07-18

Tasks 10.1-10.3 verified commit: `b935d4fd5cd07bf7550fd955e4f0efaf72c0ab8d`

OpenSpec tasks: `10.1`, `10.2`, `10.3`

Status: PASSED for tasks 10.1-10.3. Tasks 9.5, 10.4, and 10.5 remain open.

## 2026-07-18 clean-candidate verification refresh

This is an interim refresh, not completion evidence for task 10.4. The current
candidate includes the Python 3.11 comprehension audit, the content-addressed
real golden-corpus snapshot, and canonical service-test run manifests. The
candidate was integrated as local `main` commit
`89594289fd3e967633c3ed22e750ed72126631df` and pushed only to
`codex/durable-event-runtime-final`.

Local clean-worktree results:

```text
python -m scripts.dev test-workflow-domain
910 passed, 23 skipped

python -m scripts.dev test-services
336 passed, 2 skipped

python -m scripts.dev smoke
1014 passed, 23 skipped, 12 warnings
sources validate: is_valid=true, error_count=0, warning_count=0

openspec validate durable-event-runtime --strict
Change 'durable-event-runtime' is valid

openspec validate --all --strict
169 passed, 0 failed

ruff check <changed Python files>
All checks passed

git diff --check
passed
```

GitHub Actions run
`https://github.com/Devin333/NewsRoom/actions/runs/29606063125` then verified
the exact remote candidate on Linux with Python 3.11.15. Every configured step
passed: compile, Workflow runtime contracts, Workflow/Harness/Research domain,
services, RAG eval promotion, PRD daily regression, durable-event compatibility,
and fixed smoke. The job completed successfully at `2026-07-17T19:08:13Z`.

These results close the clean-checkout CI defects but do not activate authority
trust, approve rollback, prove a real compatibility observation, or qualify a
deletion deployment. Any later trust-policy, compiled-root, deployment, or
evidence change must be followed by a fresh final task 10.4 run.

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

The compatibility-release side of task 9.5 now has a deterministic verify-only
gate instead of relying on a Markdown assertion. The original two-record policy
was superseded because it made the consumer-owner decision depend on deletion
deployment facts that could exist only after that decision. Tracked policy v4
checksum
`sha256:383355c7a5382fb47448346a1da8f6c3f38475615042cbab8a5072c128d4eb1f`
pins the compatibility source, deletion boundary, and exact qualified descendant
source with their Git trees and parents, but intentionally remains
`pending_external_activation` with a null trust epoch and null governance,
observer, and consumer-owner roots. The production verifier fails closed before
evidence evaluation until a pre-existing release-security/change-control
governance bootstrap root signs trust-activation record D. D binds the positive
trust epoch, three mutually independent Ed25519 roots, exact active-policy
checksum, content-addressed verifier build, activation deployment and external
evidence. The verifier requires `activation deployed <= governance signed < A
window started`; A, B, and C each bind D's epoch and exact record checksum. The
one-way chain is therefore bootstrap governance root, signed D, signed
observation A, independent consumer-owner approval B, approved-build deployment,
and deletion deployment attestation C. The verifier still derives
query/checkpoint/projection and API/CLI/MCP/SDK/SSE inventory results from raw
facts, and also verifies all cross-record checksums, exact build plans, time
ordering, retention-through-C, distinct Ed25519 authorities,
PEM-to-pinned-root matching, and Git ancestry. The focused v4 activation and
authority-pinning suite passed `166 passed, 8 skipped`; all eight skips were
Windows symlink/reparse-point cases that require a token with link-creation
privilege and execute on capable/Linux CI hosts.

This verifier creates no external fact or decision. The three production roots,
including the bootstrap governance root, are not activated, and signed records
D/A/B/C plus their immutable external evidence URIs remain absent, so task 9.5
remains open. CLI PEM inputs cannot activate or select a trust root; they must
match the compiled bootstrap trust or the already active policy and compiled
constants.

The focused tests treat governance-signed UTC fields as trusted protocol input;
Ed25519 does not independently prove when signing occurred. Final qualification
also requires the retained activation evidence to prove the verifier build,
deployment, and activation time through a non-backfillable deployment or
transparency log, or trusted timestamp service. Repository tests and a
signer-declared JSON timestamp do not satisfy that external time anchor.

The committed rollback tool still keeps local evidence `INCOMPLETE`, but a real
approval-pending staging run has now completed for the frozen runtime candidate
`7a5956361d49e447037c89aa7edd371a7158f06d` against rollback release
`570f840c7df3870841c93e37480d7a53a67921dd`.

Canonical local evidence:
`.newsroom/durable-event-rollback-local-7a595636-final/rollback-evidence.json`

Local `evidence_checksum`:
`sha256:6ea8eb91c9efc58c3c355fc835d89c735f350d26ffedc53fd5a88a69daba3acd`

Canonical technical evidence:
`rollback-staging-7a595636-awaiting-approval/technical/technical-evidence.json`

Technical `evidence_checksum`:
`sha256:4038576aa8b8dfeeee10cb6917a03cbfd13345b595a303ce2b50fb7aa1d09e0f`

Approval request `request_checksum`:
`sha256:588f30f6377fdb1aafd23195b7916e3e634b3581333019e382516fe5ecaf3f72`

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
| Cross-release projection | candidate and rollback exact JSONL checksum `sha256:8085ba1e4db06c5993d20f24fbd8b609fa70ecdb2ccff4f27aa2c43a4ec673c4` |
| Canonical projection rows | checksum `sha256:cd3aaa6fcb10ebe489d6178f0a2ddaa5b24a905639bc4180ca46f7815768fff5` |

The earlier opt-in PostgreSQL regression remains retained, and the current
candidate staging CLI independently reached `awaiting_approval`:

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
but only after a pre-existing independent governance bootstrap root signs D and
D, the active policy, and compiled constants bind the same positive trust epoch,
three mutually independent roots, verifier build, and active-policy checksum.
D's deployment and governance signature must precede the A observation window.
The D-activated observer then signs record A, followed by independent
consumer-owner record B approving the exact qualified deletion build plan.
Only that approved build may then be deployed, after which the trusted
deployment observer must sign record C binding A, B, and the actual deployment.
Repository tests and the approval-pending rollback bundle satisfy neither this
compatibility D/A/B/C chain nor the independent rollback qualification chain.
Until both chains exist, neither PRD may be marked `IMPLEMENTED`.

## 2026-07-18 exact-candidate evidence refresh

The qualified source was refreshed before trust activation to include the
committed memory trace identity fix and the pending policy/verifier source
binding. The current evidence head is
`5c59f879b57a984e5a072952c32ac08de3b70e76`; the qualified source bound by
policy is `0a24e52b8f084099aa5f614c7a9c64081ce79ca3`.

The real PostgreSQL storage gate completed `419 passed, 9 skipped`. The real
rollback staging gate then completed `9 passed`, including cross-release worker
process, lease, projection, sequence, inbox, DLQ, and negative-gate checks. A
fresh approval-pending bundle is tracked at:

`rollback-staging-5c59f879-awaiting-approval/technical/technical-evidence.json`

```text
candidate_release_digest: 5c59f879b57a984e5a072952c32ac08de3b70e76
technical_evidence_checksum: sha256:6fb3d2fd2cd51914b183675c372534e73d89c98cf8e87233a2fc93c3e1d0d3dd
approval_request_checksum: sha256:ecd49c670115d63830e5a672b6b68d63c0db6519d13c9c202c96df1dcd09a345
postgres_database: newsroom_rollback_staging_38c36a98bd1d4ad1
projection_checksum: sha256:6a9dc458935ca9f893e0ccc19f1226e1c9f89d6a7c401592988cef43b5b088f5
```

The fixed benchmark was rerun from the exact source and passed strict verify;
its canonical JSON is `durable-event-benchmark-qualification-20260718.json`
with checksum
`sha256:a4cfb53274e5b5dada07b3feeb6f3bc87fb13630a8a7cf760fdf8cce2dba66ae`.
It recorded 15,000 SQLite appends and 60,000 appends in each PostgreSQL mode,
with zero loss, duplicate sequence, gap, or checksum failure. The full
offline suite on the runtime source completed `4442 passed, 119 skipped`;
repository smoke completed `1014 passed, 23 skipped`.

These refreshes are technical evidence only. No rollback approval, external
attestation, qualification signature, governance activation D, compatibility
observation A, consumer-owner approval B, or deletion deployment attestation C
exists.

## Disposition

- Task 10.1 is complete based on the exact-candidate full suite and refreshed
  event-runtime/staging gates above.
- Task 10.2 remains complete based on the refreshed real SQLite/PostgreSQL and
  rollback staging runs above.
- Task 10.3 is complete based on the exact-candidate strict fixed 600-second
  qualification JSON above.
- Task 10.4 remains open until task 9.5, signed governance activation D, the
  complete compatibility D/A/B/C chain, and the independent rollback
  qualification chain are complete; the final all-repository gate must then
  pass before task 10.5 updates the PRDs and final evidence.
- Task 10.5 remains open until every Definition of Done item, including task 9.5, is satisfied.
