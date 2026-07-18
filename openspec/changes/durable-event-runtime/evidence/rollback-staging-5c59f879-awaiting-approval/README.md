# Rollback staging evidence: superseded

Status: SUPERSEDED by `../rollback-staging-a2662442-awaiting-approval/`.

This bundle is the canonical technical handoff for the rollback drill run from
candidate `5c59f879b57a984e5a072952c32ac08de3b70e76` against rollback release
`570f840c7df3870841c93e37480d7a53a67921dd`.

The technical evidence is PostgreSQL-backed and records the binary switch,
sequence/checkpoint preservation, projection rebuild, external-effect
idempotency, schema/security negative gates, worker recovery, and exact-scope
cleanup. Its status is intentionally `awaiting_approval`:

```text
drill_id: rollback-drill-9579f750c1ff4973b54d0fdc3e10b34d
technical_evidence_checksum: sha256:6fb3d2fd2cd51914b183675c372534e73d89c98cf8e87233a2fc93c3e1d0d3dd
approval_request_checksum: sha256:ecd49c670115d63830e5a672b6b68d63c0db6519d13c9c202c96df1dcd09a345
```

The bundle contains no approval record, detached signature, external
attestation, qualification output, private key, or trust root. Those must be
provided by separate external authorities. The rollback approval,
deployment-attestation, and qualification chain also remains separate from the
compatibility governance root -> D -> A -> B -> deploy -> C chain.

Required continuation:

1. An independent approval authority signs the exact `technical/approval-request.json`.
2. Run `scripts.durable_event_rollback_staging finalize` with that record and trusted public key.
3. A separate deployment authority runs `attest-external`.
4. A separate release authority runs `qualify` and strict `verify`.
5. Retain the resulting signed qualification bundle or immutable external evidence URI.
