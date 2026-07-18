# Durable Event Compatibility Release Evidence

Date: 2026-07-18

OpenSpec tasks: 9.3 and 9.5

Status: AWAITING_EXTERNAL_AUTHORITY_ACTIVATION

## 2026-07-18 qualified-source refresh history

The first pre-activation refreeze used `0a24e52b8f084099aa5f614c7a9c64081ce79ca3`
and is retained only as superseded historical evidence. It must not be used for
the active deletion build because the later `a266244246b33c093905562cb9e3a514ea82703f`
candidate contains an additional production replay hardening fix.

## 2026-07-18 final qualified-source refresh

Before any external authority activation, the qualified deletion source was
refrozen again to the latest verified clean runtime candidate. The pending
policy now binds:

```text
qualified_source_commit: a266244246b33c093905562cb9e3a514ea82703f
qualified_source_tree:   140ff053f87a096a89877e044c8f527439905ca0
qualified_source_parent: e6b6d348c0511f2dc5aec2182e35154e2593c293
policy_checksum:         sha256:301a202fc6948eb22a4079c002ae0c992afe54e45a534dff7a495172ff2a6e8f
```

This is a source-identity refresh only. `authority_trust_status` remains
`pending_external_activation`, all three authority roots and `trust_epoch`
remain null, and no D/A/B/C or rollback approval/attestation/qualification
record has been accepted. Any future trust activation must bind this exact
policy checksum and content-addressed verifier/source combination.
The runtime source `a2662442...` and the later verifier source-refresh commit
are intentionally distinct: external record D must bind the content-addressed
verifier build that contains the updated policy constants, not claim that the
`a2662442...` runtime commit itself is that verifier build.

## Release candidate identity

- Compatibility release candidate: `durable-event-runtime-migration-1`
- Deployable pre-deletion commit:
  `42a8636cd72aea0c466126fc5f2d69c55db1a1d6`
- Compatibility source tree:
  `d6d2c55a965e47009d7dc8cf49582cb90e300c2d`
- Compatibility source parent:
  `f6bce48f786d5b08cc77d226b8b993e6e6b974df`
- Deletion boundary commit:
  `570f840c7df3870841c93e37480d7a53a67921dd`
- Deletion boundary tree:
  `8607c510e87c7f405519f5851949f9f5b5b5203b`
- Deletion boundary parent:
  `42a8636cd72aea0c466126fc5f2d69c55db1a1d6`
- Qualified deletion source commit:
  `a266244246b33c093905562cb9e3a514ea82703f`
- Qualified deletion source tree:
  `140ff053f87a096a89877e044c8f527439905ca0`
- Qualified deletion source parent:
  `e6b6d348c0511f2dc5aec2182e35154e2593c293`
- Canonical writer cutover commit: `1e3d0183`
- Durable run-query cutover commit: `dc47ce50`
- Tenant-scoped operator surfaces commit: `f6bce48f`

Commit `42a8636...` is the last commit before compatibility-path deletion and is
the only eligible build for the bounded migration observation. Its direct child
`570f840c...` removes the expired framework publisher/replay/callable shims,
framework `EventRecord`, storage flat `EventRecord`, and writable
`LocalJsonEventStore`.

The deletion boundary is not the deployable qualified source. Commit
`a2662442...` is a verified descendant 44 commits after the boundary and
includes the completed deletion plus subsequent runtime, Python 3.11, and
replay hardening. The tracked policy freezes all three Git identities for the
compatibility source, deletion boundary, and qualified deletion source.

These Git facts do not prove deployment or observation. No GitHub environment,
deployment, release, tag, immutable build digest, or external evidence URI
currently binds either candidate to a real deployment.

## Authority activation state

The tracked policy is deliberately fail closed:

- Schema: `newsroom.durable-event-compatibility-policy/v4`
- State: `authority_trust_status=pending_external_activation`
- `trust_epoch`: `null`
- `trusted_governance_authority`: `null`
- `trusted_observer_authority`: `null`
- `trusted_consumer_owner_authority`: `null`
- Pending-policy checksum:
  `sha256:301a202fc6948eb22a4079c002ae0c992afe54e45a534dff7a495172ff2a6e8f`

This pending policy cannot qualify D, A, B, or C. A pre-existing independent
release-security/change-control governance bootstrap root must already be pinned
in compiled production trust; policy content, an evidence bundle, record D, or a
CLI PEM cannot select it. That bootstrap root signs
`newsroom.durable-event-compatibility-trust-activation/v1` record D over exact
bytes. D binds a positive `trust_epoch`, active policy checksum, mutually
independent governance/observer/consumer-owner roots, content-addressed verifier
build, activation deployment identity/environment/time/URI, retained activation
evidence, and governance attestor identity/key/fingerprint/time.

The active policy and compiled verifier constants must pin the same
`trust_epoch`, three roots' `authority_id`, `key_id`, `algorithm=Ed25519`, and
`public_key_fingerprint`, plus the exact active-policy checksum. The activation
deployment must precede D signing, D signing must precede A's
`observation_window.started_at`, environments must match through D/A/B/C, and
D retention must extend through C signing. Pending/null/mismatched trust,
non-bootstrap D signatures, invalid verifier-build bindings, or policy/compiled
mismatches fail before A evidence evaluation.

The Ed25519 signature authenticates the governance attestor but is not itself a
trusted timestamp. Release qualification must therefore retain activation
evidence from an independently auditable, non-backfillable deployment log,
transparency log, or trusted timestamp service that binds the verifier build,
deployment identity, and activation time. The repository verifier validates the
signed digest/URI/retention bindings and ordering; it does not fetch that system
or turn a signer-declared JSON time into an RFC 3161 timestamp. If external audit
cannot prove the time anchor, D and task 9.5 remain unqualified.

### 2026-07-18 external-state audit

The current candidate code and CI are healthy, but no authority activation fact
exists. At remote candidate `89594289fd3e967633c3ed22e750ed72126631df`:

- GitHub Actions run `29606063125` passed every configured Linux/Python 3.11
  gate, including compatibility tests and fixed smoke.
- The public repository has no ruleset, protected deployment environment,
  deployment record, Actions secret or variable, webhook, release, or tag that
  establishes an independent release authority or immutable deployment.
- Repository access exposes one admin collaborator, `Devin333`; no independent
  governance, deployment-observer, or consumer-registry-owner identity is
  configured.
- The production verifier still has null compiled trust epoch, authority IDs,
  key IDs, fingerprints, and active-policy checksum. The tracked policy parses
  as `pending_external_activation` with all three roots null.
- No D/A/B/C record, detached signature, trusted public key, rollback approval
  record, external attestation, or release qualification exists under tracked
  evidence.

The canonical rollback technical handoff is now
`rollback-staging-a2662442-awaiting-approval`. Its technical evidence remains
`awaiting_approval`, with technical checksum
`sha256:0fdcef5d85bfcbdcb21e6845e0baf84f1e5a9d65c453b43f92ca7d89a99dd7b7`
and approval-request checksum
`sha256:ce98f42b4decf72de2c6b15c9f4005239b0f92ceef1c07033a65a4c338da49bc`.
The new run used PostgreSQL database `newsroom_rollback_staging_10a7bb97e8da4579`.
The former `rollback-staging-5c59f879-awaiting-approval` bundle is retained as
superseded history. Technical invariants and database presence do not
constitute the three independent rollback signatures or the separate D/A/B/C
qualification chain.

### 2026-07-18 final candidate technical refresh

The replay reducer capability audit was hardened and committed as
`a266244246b33c093905562cb9e3a514ea82703f`. The exact candidate then passed the
full offline suite (`4442 passed, 119 skipped`) and fixed smoke
(`1014 passed, 23 skipped`, source registry valid). The rollback staging run
bound to this candidate passed all seven technical external gates and remains
approval-pending; no approval, signature, attestation, qualification, private
key, or trust root was created. The fixed 600-second benchmark was separately
rerun from the same production scope and strictly verified with evidence
checksum
`sha256:7485553ad9a4ceff2bab6194e4baa48b5259b2be5af27931933daf64e3cd11e0`.

## Read cutover

- `RunInspectionService` and `WorkflowRunner` capture one fixed durable stream
  high watermark and page the complete contiguous prefix for inspection,
  replay bundles, diagnostics, health, timelines, and run comparison.
- Online reads fail explicitly when the durable store is unavailable and never
  silently treat `events.jsonl` as authoritative.
- Deleted or tampered `events.jsonl` projections do not change online results.
  Non-event artifacts remain checksum-verified in strict replay.
- API, CLI, MCP, and SSE retain compatible response fields. HTTP returns the
  stable `503 event_store_unavailable` contract; CLI returns exit code `2`
  with a bounded availability diagnostic; MCP uses the typed, redacted event
  error family.
- New checkpoints use durable 1-based stream sequence/event identity; legacy
  0-based offsets remain explicitly named import metadata with boundary
  fixtures.

## Caller and consumer observation

- Repository production callers of framework `EventRecord`: zero.
- Repository production `.subscribe(...)` callers of the synchronous event bus:
  zero. Callable compatibility coverage was test-only for the migration release.
- Framework `EventRecord`, runner-local event stores/models/factory, post-run
  indexing, and replay-to-live-bus were removed; architecture/import guards
  prevent their reintroduction.
- Repository search proves only owned-caller cleanup. It cannot prove that
  unknown external consumers stopped depending on the flat record contract.
- External consumer approval and deployment observations are not fabricated by
  repository tests. Task 9.4 implementation is complete, but release
  qualification remains pending until signed D/A/B/C records below
  exist in the required order.

## Required external evidence chain

The compatibility gate is a one-way chain. Each arrow is an exact record
checksum dependency:

```text
pre-existing governance bootstrap root
  -> D trust-activation/v1
    -> A observation/v2
      -> B consumer-signoff/v2
        -> deploy exact B-approved deletion build
          -> C deletion-deployment-attestation/v1
```

### D. Trust activation

The pre-existing governance bootstrap root signs
`newsroom.durable-event-compatibility-trust-activation/v1`. Record D binds the
active policy checksum, positive trust epoch, all three activated authority
roots, content-addressed verifier build digest/URI, activation deployment
identity/environment/time/URI, content-addressed or retention-locked activation
evidence, and the governance attestor. Its
`activation_deployment.deployed_at <= governance_attestor.signed_at`, and D must
be signed before A's observation window begins. If activation evidence is
retention locked, it remains valid beyond C's attestor signing time.

### A. Compatibility observation

The deployment observer signs
`newsroom.durable-event-compatibility-observation/v2` after a real bounded
deployment observation. Record A contains:

1. D's exact positive `trust_epoch` and `trust_activation_record_checksum`.
2. An immutable build produced from full compatibility commit
   `42a8636cd72aea0c466126fc5f2d69c55db1a1d6` and its pinned tree/parent.
3. Migration deployment environment, deployment identifier, deployment time,
   content-addressed build URI, and externally resolvable deployment URI.
4. A one-hour to seven-day UTC observation window with real API/CLI/MCP/SSE
   query, checkpoint, and projection measurements.
5. Complete deployment-registry and request/consumer-telemetry inventory for
   API/CLI/MCP/SDK/SSE, including independent ownership and zero unknown,
   unowned, or flat-record consumers.
6. Content-addressed or retention-locked external evidence plus the observer's
   trusted key fingerprint and post-observation signing time. A retention lock
   must remain valid beyond C's later attestor signing time.

Record A deliberately contains no deletion deployment. This permits it to be
completed and signed before owner approval.

### B. Consumer-owner approval

The independent consumer-registry owner signs
`newsroom.durable-event-compatibility-consumer-signoff/v2`. Record B binds A's
exact record checksum and inventory checksum, copies A's
`compatibility_release_digest` and `compatibility_build_digest`, copies every
required surface disposition, binds D's exact `trust_epoch` and
`trust_activation_record_checksum`, and approves a known immutable build plan
from qualified deletion source `a2662442...` for the same activation and target
environment.

The approved plan includes source commit/tree/parent, build digest, and
content-addressed build URI. It cannot include a future deployment identifier,
deployment time, or deployment URI. Zero registered consumers still require
this signed independent decision.

### C. Deletion deployment attestation

Only after B is signed may the approved deletion build be deployed. The
deployment observer signs
`newsroom.durable-event-compatibility-deletion-deployment-attestation/v1` after
deployment. Record C binds A and B by exact record checksum and proves that the
actual source identity, build digest/URI, and environment equal B's approved
plan. It also binds D's exact `trust_epoch` and
`trust_activation_record_checksum`. It adds the actual deployment identifier, deployment time, deployment
URI, and content-addressed or retention-locked `deployment_evidence`. The B
binding field is named `consumer_signoff_record_checksum` so it cannot be
confused with a signature-file digest. A deletion-evidence retention lock must
remain valid beyond C's attestor signing time.

The complete ordering is:

```text
activation deployed
<= governance attestation signed
<  observation started

compatibility deployed
<= observation start
<  observation end
<= observation signed
<= consumer sign-off signed
<= deletion deployed
<= deletion attestation signed
```

The rollback approval/deployment-attestation chain for task 9.5 remains
separately required. Neither chain substitutes for the other.

## Deterministic external-evidence gate

The repository provides a verify-only gate for these external inputs:

- Policy: `compatibility-observation-policy.json`
- Policy schema: `newsroom.durable-event-compatibility-policy/v4`
- Current policy state: `pending_external_activation`
- Current trust epoch and governance/observer/consumer-owner roots: `null`
- Current pending-policy checksum:
  `sha256:301a202fc6948eb22a4079c002ae0c992afe54e45a534dff7a495172ff2a6e8f`
- Verifier: `python -m scripts.durable_event_compatibility_release`
- Record schemas:
  `newsroom.durable-event-compatibility-trust-activation/v1`,
  `newsroom.durable-event-compatibility-observation/v2`,
  `newsroom.durable-event-compatibility-consumer-signoff/v2`, and
  `newsroom.durable-event-compatibility-deletion-deployment-attestation/v1`
- Operator template:
  `scripts/templates/durable_event_compatibility_observation.md`
- New CLI inputs: `--authority-activation`,
  `--authority-activation-signature`, `--trusted-governance-public-key`,
  `--deletion-attestation`, and `--deletion-attestation-signature`
- Successful evidence URI outputs: `trust_activation_evidence_uri`,
  `observation_external_evidence_uri`, and `deletion_deployment_evidence_uri`

Record D uses a detached Ed25519 signature from the pre-existing governance
bootstrap root. Records A and C use the activated deployment-observer root;
record B uses the activated consumer-registry-owner root. All three authorities'
IDs, key IDs, and fingerprints must be mutually distinct. Signatures cover exact
record bytes; record checksums cover canonical field content. In production,
the positive trust epoch, all three activated roots, and the active policy
checksum must match policy and compiled verifier constants before A/B/C
signatures are considered. The
`--trusted-governance-public-key`,
`--trusted-observer-public-key` and `--trusted-consumer-owner-public-key` PEM
arguments provide the bytes for those pre-pinned roots; they do not authorize
the evidence bundle or CLI caller to choose a root.

The verifier derives the gate from bootstrap governance authorization, trust
epoch and activation-record binding, verifier build/deployment binding,
source/build/deployment binding,
sequence/watermark, fallback, checkpoint-base, legacy-offset,
projection-secret/write-back, inventory completeness, owner decision, temporal
ordering, retention, checksum, and signature facts. It does not generate keys,
identities, decisions, observations, attestations, or signatures. It also
resolves the tracked commits from the local Git object database, verifies every
tree and direct parent, and proves the deletion boundary is an ancestor of the
qualified source with `git merge-base --is-ancestor`.

The gate therefore remains first awaiting an externally signed D activation
record and then real A/B/C evidence. Adding the verifier, passing PEM paths, or
updating this document does not activate trust or qualify the deletion release.

## Verification scope

Repository regression coverage verifies fixed-watermark pagination,
stream/tenant/cursor validation, store unavailability, JSONL
deletion/tampering, strict non-event artifact integrity, API/CLI/MCP
compatibility, and absence of expired record/writer exports. The compatibility
verifier additionally rejects malformed JSON, duplicate keys, non-finite
numbers, unexpected fields, oversized or non-regular files, symlinks, bad
checksums/signatures, authority reuse, cross-record mismatch, and invalid time
order.

These local results qualify only the code path. They do not complete the real
trust activation, compatibility observation, consumer approval, deletion deployment attestation,
rollback drill, or final task 10.5 evidence update.
