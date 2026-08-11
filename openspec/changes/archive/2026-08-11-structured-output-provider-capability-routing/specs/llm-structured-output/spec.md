## MODIFIED Requirements

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
