# llm-structured-output Specification

## Purpose
TBD - created by archiving change llm-structured-output. Update Purpose after archive.
## Requirements
### Requirement: LLM requests can declare structured output
The system SHALL compile every output schema before transport and SHALL translate structured-output requests only through a versioned capability profile and immutable provider projection. A projection MUST identify its mode, contract and capability revisions, stable digest, and enforced/omitted keyword coverage. Unsupported enforcement MUST route to an eligible deployment, use an explicitly authorized JSON-object-plus-local-gate projection, or fail closed without transport; it MUST NOT silently drop schema constraints.

#### Scenario: Native strict projection is fully eligible
- **WHEN** the resolved deployment covers the contract dialect, references, limits, and every required enforcement keyword
- **THEN** the OpenAI-compatible payload contains the projected strict JSON schema and records matching contract, capability, and projection identities

#### Scenario: JSON object local gate is explicitly authorized
- **WHEN** native enforcement is unavailable and request policy explicitly permits JSON-object-plus-local-gate mode
- **THEN** the provider receives JSON object mode, the projection exposes all provider-omitted enforcement keywords, and the full canonical schema remains mandatory for local terminal validation

#### Scenario: Provider projection is ineligible
- **WHEN** a deployment cannot cover the required contract and local-only mode is not authorized
- **THEN** the router re-projects for the next configured deployment or raises a non-retryable provider-schema-ineligible error without calling that provider

#### Scenario: Fallback deployment is evaluated independently
- **WHEN** a primary deployment is ineligible and a fallback has a different capability revision
- **THEN** the router builds a new projection and reruns context admission for the fallback rather than reusing the primary projection

### Requirement: Structured responses are normalized
The system SHALL normalize structured response text into accepted output only after strict JSON-object decoding and validation against the request's compiled local contract. Complete and streaming terminal paths MUST use the same contract and projection identities, decoder, validator, typed adapter, diagnostics, and validation metadata. Streaming fragments MUST remain provisional and MUST NOT expose a verified structured object.

#### Scenario: Complete and stream terminal outputs are equivalent
- **WHEN** complete and stream return the same valid terminal JSON for the same contract and projection
- **THEN** both expose the same validated object and matching contract/projection validation metadata

#### Scenario: Stream emits provisional fragments
- **WHEN** a structured stream emits text before completion
- **THEN** each non-terminal event is marked provisional and carries no verified structured output

#### Scenario: Stream terminal validation fails
- **WHEN** an accumulated structured stream is incomplete, invalid JSON, or violates the local contract
- **THEN** no verified terminal event is emitted and the deterministic structured-output error is not retried as a transport failure

### Requirement: Daily report drafting can consume structured output
The system SHALL prefer structured LLM output for daily live report drafts when available.

#### Scenario: LLM response contains structured report
- **WHEN** daily live drafting receives `structured_output`
- **THEN** it uses that object instead of reparsing raw text

### Requirement: Structured output cache preserves contract identity and validation
The LLM cache SHALL isolate structured output by the canonical contract and provider projection identity, SHALL persist that identity with the entry, and SHALL validate the terminal object before write and after read. Unmanaged requests, identity mismatches, or invalid entries SHALL fail closed without producing a cache hit.

#### Scenario: Contract revision changes
- **WHEN** an otherwise identical request uses a different schema digest, schema revision, typed-adapter revision, provider capability revision, or projection digest
- **THEN** it resolves to a different cache identity and cannot reuse the previous entry

#### Scenario: Cached structured output is corrupt
- **WHEN** a stored entry fails identity verification or canonical local validation
- **THEN** the lookup is reported as a corrupt miss and the entry is deleted best effort
- **AND** no accepted or publication side effect is authorized by the entry

#### Scenario: Structured output write is unverified
- **WHEN** a response lacks a managed validation envelope or fails the compiled contract
- **THEN** the cache skips the write with a stable validation reason

### Requirement: Structured output observability is redacted and replayable
The managed structured-output path SHALL expose allowlisted redacted events and low-cardinality metrics for contract compilation, provider projection, decoding, local and typed validation, repair, cache validation, and acceptance. Replay data SHALL identify the attempt and contract/projection revisions without containing raw output, schema bodies, prompts, secrets, tool payloads, tenant names, or evidence bodies.

#### Scenario: Structured output validation fails
- **WHEN** decode, local schema, or typed validation rejects a candidate
- **THEN** the event records the stable stage, issue code and bounded JSON Pointer paths, issue count, response fingerprint, revision identities, and timestamp
- **AND** metric labels contain only approved bounded mode, outcome, code, validator, and provider values

#### Scenario: Structured output succeeds through cache
- **WHEN** a cache hit is identity-verified and locally revalidated
- **THEN** replay records a successful cache validation and subsequent Harness acceptance or domain/evidence rejection as separate dispositions

### Requirement: Production structured output uses one managed path
Production callers SHALL NOT directly parse LLM response text or invoke compatibility schema validators to reconstruct structured output. They SHALL consume only managed validated terminal output and SHALL preserve later deterministic domain and evidence gates.

#### Scenario: Production caller bypass is introduced
- **WHEN** production source directly parses `response.content` as JSON or locally revalidates LLM structured output outside the approved framework owners
- **THEN** the architecture test fails with the source location and bypass category

#### Scenario: Research candidate passes schema but fails evidence scope
- **WHEN** a managed Research candidate is structurally valid but references evidence outside the bounded request scope
- **THEN** the Research domain/evidence gate rejects it and no report or artifact is published

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
