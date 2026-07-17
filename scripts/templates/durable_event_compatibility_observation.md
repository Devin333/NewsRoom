# Durable Event Compatibility Observation Evidence

> Evidence status: EXTERNAL INPUT REQUIRED
>
> OpenSpec change: `durable-event-runtime`
>
> Task: `9.5`

This gate is separate from rollback qualification. It verifies the real bounded
migration-release observation and external-consumer sign-off required before
the deletion release can qualify. Repository tests, local deployments, Markdown
claims, and locally generated signatures do not satisfy it.

## Trusted policy

Use the tracked policy without weakening or replacing it:

```text
openspec/changes/durable-event-runtime/evidence/compatibility-observation-policy.json
```

The policy pins:

- migration commit `42a8636cd72aea0c466126fc5f2d69c55db1a1d6` and its Git tree;
- deletion commit `570f840c7df3870841c93e37480d7a53a67921dd`, its Git tree, and direct parent;
- a one-hour minimum and seven-day maximum observation window;
- at most 1,000 records per query/checkpoint/projection evidence family;
- real API, CLI, MCP, and SSE query observations;
- API, CLI, MCP, SDK, and SSE consumer inventory coverage;
- deployment-registry and request/consumer-telemetry inventory sources.

## External records

The deployment/observation authority produces
`compatibility-observation.json` with schema
`newsroom.durable-event-compatibility-observation/v1`. It must bind:

- immutable source commit/tree, build digest and content-addressed build URI;
- migration deployment identity, environment, time, and external URI;
- a finite observation window;
- query measurements proving durable-store authority, successful responses,
  no projection fallback, and sequence at or below the fixed source watermark;
- checkpoint measurements proving 1-based durable sequence/event identity,
  no legacy offset use, and sequence at or below the source watermark;
- projection measurements proving store/manifest/projection watermark equality,
  ordered/projection checksums, zero secret findings, and zero store write-back;
- complete consumer inventory with zero unknown, unowned, or flat-record reads;
- deletion build/deployment identity in the same environment after observation
  and owner sign-off;
- a retention-locked or content-addressed external evidence URI;
- the deployment observer identity, trusted key fingerprint, and signing time.

The consumer-registry owner separately produces `consumer-signoff.json` with
schema `newsroom.durable-event-compatibility-consumer-signoff/v1`. It binds the
policy, both release digests, exact observation and inventory checksums, every
required surface, and an `approved` decision. Zero consumers still require this
independent signed registry attestation.

Each record is signed over its exact file bytes with a detached Ed25519
signature. The deployment-observer and consumer-owner public keys must have
different fingerprints and remain controlled by different authorities. Private
keys do not enter this repository, the evidence bundle, or the verifier host.

## Strict verification

```powershell
.\.venv\Scripts\python.exe -m scripts.durable_event_compatibility_release `
  --policy openspec/changes/durable-event-runtime/evidence/compatibility-observation-policy.json `
  --observation <external>/compatibility-observation.json `
  --observation-signature <external>/compatibility-observation.sig `
  --trusted-observer-public-key <trust>/observer-public.pem `
  --consumer-signoff <external>/consumer-signoff.json `
  --consumer-signoff-signature <external>/consumer-signoff.sig `
  --trusted-consumer-owner-public-key <trust>/consumer-owner-public.pem
```

Exit code `0` means the signed records satisfy the deterministic gate. Exit code
`1` means the evidence is invalid or incomplete. The verifier never generates
keys, decisions, observation records, owner identities, or signatures.
