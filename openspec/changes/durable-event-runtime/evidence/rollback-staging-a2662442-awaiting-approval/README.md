# Rollback staging evidence: awaiting approval

This bundle is the latest PostgreSQL-backed technical handoff for candidate
`a266244246b33c093905562cb9e3a514ea82703f` against rollback release
`570f840c7df3870841c93e37480d7a53a67921dd`.

The drill completed at `2026-07-18T05:49:10.654983Z` and retained the accepted
event prefix, stream sequence continuity, delivery/checkpoint/inbox/DLQ state,
crash recovery, concurrent-writer continuity, projection rebuild, schema and
security rejection gates, and external-effect idempotency checks. The
technical evidence is intentionally still `awaiting_approval`:

```text
drill_id: rollback-drill-fa9bc85a26d54ff19acc77e0bc8e8d32
technical_evidence_checksum: sha256:0fdcef5d85bfcbdcb21e6845e0baf84f1e5a9d65c453b43f92ca7d89a99dd7b7
approval_request_checksum: sha256:ce98f42b4decf72de2c6b15c9f4005239b0f92ceef1c07033a65a4c338da49bc
```

This bundle contains no approval record, detached signature, external
attestation, qualification output, private key, or trust root. An independent
approval system must review `technical/approval-request.json`, produce the exact
`newsroom.durable-event-rollback-approval/v1` `approval-record.json`, and have
the approval authority sign the exact approval-record bytes. The approval
request is review input, not the detached-signature payload. The staging
`finalize` step then verifies the record and signature before independent
deployment attestation, release qualification, and strict verification. This
rollback chain is separate from the compatibility governance
`D -> A -> B -> deploy -> C` chain; neither chain substitutes for the other.
