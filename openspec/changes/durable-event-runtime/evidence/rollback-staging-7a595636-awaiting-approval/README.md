# Rollback staging evidence: awaiting approval

This directory freezes the technical output of the PostgreSQL staging rollback
drill for runtime candidate `7a5956361d49e447037c89aa7edd371a7158f06d` and
rollback release `570f840c7df3870841c93e37480d7a53a67921dd`.

This bundle supersedes `rollback-staging-fbdec37a-awaiting-approval` as the
canonical approval handoff. The earlier candidate predates the committed
compatibility-release evidence verifier and policy binding. The still-earlier
`rollback-staging-524afab7-awaiting-approval` bundle remains historical only.

The bundle is intentionally **not** release qualification evidence. Its status
is `awaiting_approval`; it contains no approval record, detached approval
signature, external attestation, qualification signature, private key, or trust
root. OpenSpec task 9.5 remains incomplete until independent authorities finish
that chain and the separate compatibility-release observation is complete.

## Directory contract

- `technical/` is the exact frozen input for the approval handoff. The staging
  verifier validates `technical-evidence.json` and all eight referenced
  artifacts.
- `audit/native/` contains controller and worker output retained for technical
  review. It is not an approval input and cannot replace the technical manifest.
- `audit/projections/` contains the exact candidate and rollback `events.jsonl`
  bytes. Their equality proves the portable projection-byte comparison recorded
  by this run.
- `manifest.json` records SHA-256 over the exact bytes and size of all 18 copied
  evidence files. These byte checksums are distinct from canonical object
  checksums embedded inside the technical evidence and approval request.

## Deliberate exclusions

`staging-config.json`, SQLite databases, the external-effect database, release
worktrees, and generated caches are not copied. They contain machine-local
paths, mutable runtime state, or full source trees and are not part of the
portable approval input. The technical PostgreSQL, delivery, effect, traffic,
orchestrator, negative-gate, and projection facts remain represented by the
frozen JSON artifacts.

## Required external continuation

1. A real approval authority must produce the exact
   `newsroom.durable-event-rollback-approval/v1` record, detached Ed25519
   signature, and trusted approval public key.
2. Run `scripts.durable_event_rollback_staging finalize` against this frozen
   `technical/technical-evidence.json`.
3. A separate deployment authority must run `attest-external` with a second
   trust root.
4. A separate release authority must run `qualify` with a third trust root.
5. Run strict `verify` and retain the resulting signed qualification bundle or
   an immutable external evidence URI before completing task 9.5.
6. Complete the independently evidenced compatibility deployment observation
   and external-consumer sign-off described in `../compatibility-release.md`.
