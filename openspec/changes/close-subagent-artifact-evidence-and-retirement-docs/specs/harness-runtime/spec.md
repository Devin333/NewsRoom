## ADDED Requirements

### Requirement: Canonical Subagent Artifact Evidence

Harness SHALL resolve every non-empty artifact reference carried by a subagent candidate through an explicitly injected read-only canonical artifact verifier before accepting the candidate or replaying its TaskPlan history. Verification MUST enforce canonical reference syntax, accepted parent-run binding, manifest identity, declared size, checksum, and stored bytes; it MUST NOT return artifact payloads, grant publication visibility, invoke a worker, or create a competing artifact owner.

#### Scenario: Subagent artifact evidence is accepted

- **WHEN** a durable subagent output contains an artifact ref owned by the accepted parent run and the canonical verifier validates its manifest and bytes
- **THEN** TaskPlan MAY continue deterministic result verification
- **AND** the verifier MUST NOT publish the artifact or expose its payload to the subagent transcript reader

#### Scenario: Artifact evidence cannot be resolved

- **WHEN** a non-empty subagent artifact ref is malformed, missing, cross-run, stale, corrupt, or no canonical verifier is available
- **THEN** Harness MUST fail closed with a stable artifact-verification reason before committing a TaskResult
- **AND** the parent stage MUST record a durable controlled failure without falling back to string equality or process-local state

#### Scenario: Offline replay revalidates artifact evidence

- **WHEN** offline replay encounters a versioned subagent result with artifact refs
- **THEN** it MUST resolve those refs again through the canonical verifier using the recorded parent run identity
- **AND** live worker, tool, memory-write, retrieval, and publication call counts MUST remain zero
