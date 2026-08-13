## ADDED Requirements

### Requirement: TaskPlan Verifies Subagent Artifact References

TaskPlan SHALL treat subagent artifact references as evidence owned by the canonical artifact store, not as self-authenticating URI strings. For every non-empty artifact ref, deterministic result verification and replay MUST require an `ArtifactReferenceVerifierPort`, bind the check to `TaskResultRecord.run_id`, and reject the candidate or history when the owner cannot verify the reference. Empty artifact-ref tuples SHALL remain valid and non-subagent result behavior SHALL remain unchanged.

#### Scenario: Worker and transcript repeat a fabricated ref

- **WHEN** a subagent worker result and its durable output document contain the same fabricated artifact URI
- **THEN** TaskPlan MUST reject the result with `task_plan_subagent_artifact_unverified`
- **AND** it MUST NOT append an accepted or rejected TaskResult for that unverified candidate

#### Scenario: Artifact verifier is not configured

- **WHEN** a subagent output contains artifact refs but TaskPlan has no canonical artifact verifier
- **THEN** deterministic result verification or replay MUST fail closed with `task_plan_subagent_artifact_verifier_required`
- **AND** string equality among output, result, and event records MUST NOT satisfy the evidence requirement

#### Scenario: Replay artifact integrity has changed

- **WHEN** a previously recorded artifact ref no longer resolves with the recorded run identity, manifest, checksum, or bytes
- **THEN** TaskPlan replay MUST fail with `task_plan_subagent_artifact_unverified`
- **AND** it MUST NOT report the stage as verified or call the live subagent again
