## MODIFIED Requirements

### Requirement: Context Engineering Assembly
Harness SHALL assemble worker context from explicit stable-prefix and dynamic-tail semantic groups. Global policy, workflow route table, current task/step contract, schemas, gate definitions, tool allowlists, memory namespace policy, source refs, required evidence, unresolved tool transactions, retry/replan state, and budget values MUST NOT be compressed away or placed only in unverified dynamic summaries. Every structural or lossy transformation MUST produce an immutable result snapshot and pass versioned structure, protection, tool-transaction, provenance, evidence/loss, bounded-action, replay-integrity, and deployment-aware physical-admission gates before Harness records `context_compaction_verified` or authorizes provider dispatch.

#### Scenario: Critical control material survives compression
- **WHEN** context budget pressure requires compression
- **THEN** Harness MUST preserve policy, schema, gate, allowlist, namespace, source ref, and budget sections verbatim or through lossless references
- **AND** dynamic worker outputs MAY be summarized only outside the stable prefix through a structured candidate and deterministic verification

#### Scenario: Post-compaction budget still fails
- **WHEN** a compaction result passes structure and evidence gates but the resolved deployment preparation still exceeds its effective input budget
- **THEN** Harness MUST record a rejected compaction outcome
- **AND** MUST NOT write a verified snapshot or call the provider with that result

#### Scenario: Pending tool transaction is present
- **WHEN** context pressure affects an assistant tool-call transaction whose result is pending or unresolved
- **THEN** Harness MUST preserve the complete transaction state as protected context
- **AND** MUST choose another bounded action or fail closed

#### Scenario: Verified context event cannot commit
- **WHEN** every deterministic gate passes but the canonical durable transcript/event append fails
- **THEN** Harness MUST NOT treat the result snapshot as active or authorize provider dispatch
