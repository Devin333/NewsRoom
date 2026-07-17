# Durable Event Compatibility Observation Evidence

> Evidence status: EXTERNAL INPUT REQUIRED
>
> OpenSpec change: `durable-event-runtime`
>
> Task: `9.5`

This gate is separate from rollback qualification. It verifies the real bounded
migration-release observation and external-consumer approval required before a
deletion build may qualify. Repository tests, local deployments, Markdown
claims, and locally generated identities or signatures do not satisfy it.

The evidence protocol is a one-way trust activation plus three-record release
chain. Do not let activation roots self-authorize, add a deletion deployment to
record A, or make record B depend on future deployment facts:

```text
pre-existing governance bootstrap root
  -> D compatibility-trust-activation/v1 (governance attestor)
    -> A compatibility-observation/v2 (deployment observer)
      -> B compatibility-consumer-signoff/v2 (consumer-registry owner)
        -> deploy exact B-approved deletion build
          -> C deletion-deployment-attestation/v1 (deployment observer)
```

## Trusted policy

Use the tracked policy without weakening or replacing it:

```text
openspec/changes/durable-event-runtime/evidence/compatibility-observation-policy.json
```

The tracked v4 policy is not active yet:

```text
authority_trust_status=pending_external_activation
trust_epoch=null
trusted_governance_authority=null
trusted_observer_authority=null
trusted_consumer_owner_authority=null
policy_checksum=sha256:383355c7a5382fb47448346a1da8f6c3f38475615042cbab8a5072c128d4eb1f
```

Production verification fails with `authority_trust_not_activated` while this
state remains. Do not begin record A's observation window under the pending
policy. A release-security/change-control governance bootstrap root must already
exist in compiled production trust and remain independent from observer and
consumer-owner roots. No policy value, record D, evidence bundle, or CLI PEM may
select that bootstrap root.

The bootstrap root signs exact bytes of
`newsroom.durable-event-compatibility-trust-activation/v1` record D. D binds the
active policy checksum, positive `trust_epoch`, mutually independent governance,
observer, and consumer-owner roots, content-addressed verifier build, activation
deployment/environment/time/evidence, and governance attestor. The same trust
epoch, authority/key IDs, `algorithm=Ed25519`, fingerprints, and active-policy
checksum must be pinned in active policy and compiled production-verifier
constants. D activation deployment must occur before D signing; D signing must
occur before `observation_window.started_at`; all D/A/B/C environments must
match; D retention must cover C. A later D cannot make an earlier observation
window eligible.

An Ed25519 signature authenticates the governance attestor but does not create a
trusted timestamp. `activation_evidence` must therefore point to an
independently auditable, non-backfillable deployment log, transparency log, or
trusted timestamp service that binds the verifier build, deployment identity,
and activation time. The local verifier checks D's signed checksum, URI,
retention, and ordering bindings; release governance must separately verify the
retained external time anchor before task 9.5 can pass.

The policy pins:

- migration candidate commit `42a8636cd72aea0c466126fc5f2d69c55db1a1d6`
  and its Git tree and parent;
- deletion boundary commit `570f840c7df3870841c93e37480d7a53a67921dd`
  and its Git tree and parent;
- qualified deletion source commit
  `0a24e52b8f084099aa5f614c7a9c64081ce79ca3`, its Git tree and parent;
- that the qualified deletion source is a descendant of the deletion boundary;
- a one-hour minimum and seven-day maximum observation window;
- at most 1,000 records per query/checkpoint/projection evidence family;
- real API, CLI, MCP, and SSE query observations;
- API, CLI, MCP, SDK, and SSE consumer inventory coverage;
- deployment-registry and request/consumer-telemetry inventory sources.

The active policy pins the only governance, observer, and consumer-owner
authorities permitted in the chain. All three authority IDs, key IDs, and
fingerprints must be mutually distinct.

The deletion boundary identifies where compatibility code was removed. The
qualified deletion source identifies the exact later source snapshot from which
the approved and deployed build must be produced. A build from the boundary
commit alone does not satisfy this policy.

## Record D: trust activation

The release-security/change-control governance authority produces
`authority-activation.json` with schema
`newsroom.durable-event-compatibility-trust-activation/v1`. Its exact top-level
fields are:

- `schema`, `status`, `release_id`, `policy_checksum`, and positive
  `trust_epoch`;
- `trusted_governance_authority`, `trusted_observer_authority`, and
  `trusted_consumer_owner_authority`, each with `authority_id`, `key_id`,
  `algorithm=Ed25519`, and `public_key_fingerprint`;
- `activation_deployment`, containing `deployment_id`, `environment`,
  `deployed_at`, content-addressed `verifier_build_digest` and
  `verifier_build_uri`, and externally resolvable `deployment_uri`;
- content-addressed or retention-locked `activation_evidence`;
- `governance_attestor`, containing `attestor_id`, `key_id`,
  `public_key_fingerprint`, and `signed_at`;
- `record_checksum`, computed over the canonical record without that field.

The governance bootstrap root signs D's exact bytes. The activation deployment
precedes governance signing, governance signing precedes A's observation
window, and retained activation evidence remains valid through C signing.

## Record A: compatibility observation

The deployment/observation authority produces
`compatibility-observation.json` with schema
`newsroom.durable-event-compatibility-observation/v2`. It contains only facts
available before deletion deployment and binds:

- `release_id` and the exact active tracked `policy_checksum` established before
  the observation window starts;
- D's exact positive `trust_epoch` and
  `trust_activation_record_checksum`;
- `compatibility_release`, including source commit/tree/parent, content-addressed
  build digest/URI, deployment identity, environment, deployment time, and
  externally resolvable deployment URI;
- `observation_window`, with finite UTC start/end values and exact duration;
- `observations.queries`, proving durable-store authority, successful responses,
  no projection fallback, and sequence at or below the fixed source watermark;
- `observations.checkpoints`, proving 1-based durable sequence/event identity,
  no legacy offset use, and sequence at or below the source watermark;
- `observations.projections`, proving store/manifest/projection watermark
  equality, ordered/projection checksums, zero secret findings, and zero store
  write-back;
- `consumer_inventory`, covering every required source and surface with zero
  unknown consumers, unowned consumers, or flat-record reads;
- `external_evidence`, whose URI is content-addressed or retention-locked; if
  locked, `retention_until` must be later than record C's attestor signing time;
- `deployment_observer`, including the observer identity, trusted observer-key
  fingerprint, and signing time;
- `record_checksum`, computed over the canonical record without that field.

The observer signs the exact JSON file bytes with the trusted observer Ed25519
key. Record A must not contain a deletion deployment, owner decision, or facts
that can exist only after owner approval.

## Record B: consumer sign-off

After record A is signed, the independent consumer-registry owner produces
`consumer-signoff.json` with schema
`newsroom.durable-event-compatibility-consumer-signoff/v2`. It binds:

- `release_id`, `policy_checksum`, `compatibility_release_digest`, and
  `compatibility_build_digest`, each equal to record A where applicable, plus
  record A's exact `observation_record_checksum`;
- D's exact positive `trust_epoch` and
  `trust_activation_record_checksum`;
- the exact `consumer_inventory.inventory_checksum`, registry identity, and
  complete API/CLI/MCP/SDK/SSE surface dispositions copied from record A;
- `approved_deletion_release`, containing the qualified deletion source
  commit/tree/parent, build digest, content-addressed build URI, and target
  environment;
- an `approved` decision, registry-owner identity, trusted consumer-owner-key
  fingerprint, UTC signing time, and its own `record_checksum`.

`approved_deletion_release` is an approval of a known immutable build plan. It
must not contain a future deployment ID, deployment time, or deployment URI.
Zero consumers still require this independent signed registry attestation.

## Record C: deletion deployment attestation

Only after record B is signed may the approved build be deployed. The
deployment/observation authority then produces `deletion-attestation.json` with
schema `newsroom.durable-event-compatibility-deletion-deployment-attestation/v1`.
It binds:

- the same release and policy, record A's exact `observation_record_checksum`,
  and record B's exact `consumer_signoff_record_checksum`;
- D's exact positive `trust_epoch` and
  `trust_activation_record_checksum`;
- `deletion_release`, whose source commit/tree/parent, build digest, build URI,
  and environment exactly match B's `approved_deletion_release`;
- the actual deployment ID, deployment time, and externally resolvable
  deployment URI;
- content-addressed or retention-locked `deployment_evidence` for the deletion
  deployment; if locked, `retention_until` must be later than record C's
  attestor signing time;
- `deployment_attestor`, including the deployment-observer identity, trusted
  observer-key fingerprint, and post-deployment signing time;
- top-level `record_checksum`, computed over the canonical record without that
  field.

The pre-existing governance bootstrap key verifies D. The activated observer key
verifies A and C, and the activated independent consumer-owner key verifies B.
All three fingerprints, key IDs, and signer identities must be distinct; no
private key may enter this repository, the evidence bundle, or the verifier
host.

## Required ordering

Every deployment, observation, and signature timestamp is UTC, cannot be in the
future beyond the verifier's bounded clock-skew allowance, and must satisfy:

```text
activation_deployment.deployed_at
<= governance_attestor.signed_at
<  observation_window.started_at

compatibility_release.deployed_at
<= observation_window.started_at
<  observation_window.ended_at
<= deployment_observer.signed_at
<= consumer_signoff.signed_at
<= deletion_release.deployed_at
<= deployment_attestor.signed_at
```

`retention_until` is an expiry bound rather than an event timestamp. In
`retention_locked` mode it must be later than the signing time it protects; D's
activation-evidence lock and A's observation-evidence lock must both extend
beyond C's attestor signing time.

Record checksums bind canonical field content. Detached Ed25519 signatures bind
the exact file bytes, so changing whitespace or line endings after signing
invalidates the signature. Evidence JSON must also satisfy the verifier's exact
field set, duplicate-key, finite-number, regular-file, symlink, and size rules.

## Strict verification

Run the verifier from a Git checkout that retains the pinned compatibility,
deletion-boundary, and qualified-deletion objects. In addition to comparing the
policy values with compiled trust constants, the verifier resolves each Git
tree and direct parent and proves the boundary is an ancestor of the qualified
source with `git merge-base --is-ancestor`.

The PEM files passed through `--trusted-governance-public-key`,
`--trusted-observer-public-key`, and `--trusted-consumer-owner-public-key` are key
material for already pinned roots. The verifier hashes each PEM's Ed25519 public
key and requires the fingerprint to equal compiled bootstrap trust or both the
active policy root and compiled constant. PEMs inside or selected by the
evidence bundle do not establish trust, and changing a CLI path cannot select a
different authority.

```powershell
.\.venv\Scripts\python.exe -m scripts.durable_event_compatibility_release `
  --policy openspec/changes/durable-event-runtime/evidence/compatibility-observation-policy.json `
  --authority-activation <external>/authority-activation.json `
  --authority-activation-signature <external>/authority-activation.sig `
  --trusted-governance-public-key <trust>/governance-public.pem `
  --observation <external>/compatibility-observation.json `
  --observation-signature <external>/compatibility-observation.sig `
  --trusted-observer-public-key <trust>/observer-public.pem `
  --consumer-signoff <external>/consumer-signoff.json `
  --consumer-signoff-signature <external>/consumer-signoff.sig `
  --trusted-consumer-owner-public-key <trust>/consumer-owner-public.pem `
  --deletion-attestation <external>/deletion-attestation.json `
  --deletion-attestation-signature <external>/deletion-attestation.sig
```

Exit code `0` means signed D/A/B/C records satisfy the deterministic gate.
Exit code `1` means the evidence is invalid or incomplete. The verifier never
generates trust activation, keys, decisions, observation records, deployment
attestations, governance/owner/observer identities, or signatures. A successful
result identifies all three retained evidence locations as
`trust_activation_evidence_uri`, `observation_external_evidence_uri`, and
`deletion_deployment_evidence_uri`.
