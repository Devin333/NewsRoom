## ADDED Requirements

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
