## ADDED Requirements

### Requirement: Provider enforcement releases are evaluation-gated and reversible
Native strict and constrained provider enforcement SHALL be eligible only when the deployment capability references an immutable Harness-approved release record whose provider, deployment, capability revision, projection mode, workflow scope, corpus, baseline, and evaluation identities match the attempted projection. Disabled, shadow, held, revoked, missing, or mismatched records SHALL NOT authorize provider enforcement. Rollback SHALL preserve strict decoding and canonical local validation.

#### Scenario: Approved provider enforcement is selected
- **WHEN** a native or constrained capability has an enabled approved release whose identity and workflow scope match the request
- **THEN** the router may select the provider projection and records the release, rollout, evaluation, and rollback identities
- **AND** the terminal response still passes the canonical local and typed gates

#### Scenario: Capability is in shadow
- **WHEN** a capability has a shadow release record
- **THEN** the system records the candidate projection and comparison identity but does not send native/constrained enforcement to the provider
- **AND** the actual request uses an independently eligible deployment, an explicitly authorized JSON-object local gate, or fails closed

#### Scenario: Release evidence does not match
- **WHEN** the release is absent, not approved, out of scope, revoked, or bound to different capability/corpus/evaluation identities
- **THEN** native/constrained projection is rejected before transport with a stable release-ineligible diagnostic

#### Scenario: Provider enforcement is rolled back
- **WHEN** a configured rollback trigger is reached
- **THEN** Harness selects the recorded previous capability, JSON-object local gate, alternate deployment, or reject action
- **AND** local strict decoding, schema validation, typed validation, and durable attempt records remain enabled

### Requirement: Provider release evaluation is reproducible and multi-dimensional
The system SHALL evaluate provider enforcement with versioned provenance-bearing schema and held-out Research observations. It SHALL independently gate schema validity, first-pass validity, repair success, answer quality, evidence grounding, citation completeness, provider rejection, latency, token usage, and monetary cost against explicit thresholds and baselines. No metric improvement SHALL compensate for another failed gate.

#### Scenario: All release gates pass
- **WHEN** replayed observations match their corpus and baseline identities and every required metric passes
- **THEN** the deterministic report is promotion-eligible and exposes stable case, metric, gate, and report digests

#### Scenario: Structured validity improves but Research quality regresses
- **WHEN** schema metrics pass but answer quality, evidence grounding, or citation completeness violates its threshold or regression tolerance
- **THEN** the report is not promotion-eligible and no enabled release can be created

#### Scenario: Evidence corpus is tampered with
- **WHEN** a corpus, observation set, baseline, report, or release payload no longer matches its declared digest
- **THEN** replay or release loading fails closed before provider enforcement can be enabled

#### Scenario: Live provider evidence is unavailable
- **WHEN** a production deployment has no reviewed live evaluation evidence
- **THEN** its release remains held, disabled, or shadow-only and cannot be described as production-approved
