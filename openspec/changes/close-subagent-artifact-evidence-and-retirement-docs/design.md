## Context

The durable subagent transcript change made transcript and candidate-output documents immutable, readable, and checksum-bound. `SubAgentOutputDocument.artifact_refs`, however, are still plain strings. `TaskPlanResultVerifier` currently checks only that the worker result and durable output contain the same tuple, and `TaskPlanReplayReducer` checks event/result tuple equality. A fabricated URI can therefore become accepted lineage even though no artifact owner can resolve it.

Research already has the canonical filesystem artifact owner. Its normal `read_artifact()` path combines integrity checks with terminal publication visibility, which is intentionally unavailable while a dynamic analysis stage is still running. TaskPlan needs a narrower read-only integrity operation that verifies ownership without returning content or granting publication visibility.

The obsolete agent session runtime has been removed. Historical `.newsroom/paper-agent-sessions.sqlite3` files may still exist on operator-managed installations, but they are no longer live runtime state and must not be automatically deleted by application startup or migration code.

## Goals / Non-Goals

**Goals:**

- Reject every non-empty subagent artifact ref unless the canonical owner verifies its syntax, parent-run binding, manifest metadata, checksum, size, and stored bytes.
- Apply the same verification during TaskPlan acceptance, recovery, and offline replay without a live worker call.
- Keep verification read-only, payload-free, and independent from publication authorization.
- Persist a stable parent `TASK_PLAN_HALTED` event when transcript or artifact evidence cannot be verified.
- Document and test the operator-owned disposition of historical agent-session SQLite data.

**Non-Goals:**

- Do not recreate a shared-session store, workspace, lifecycle, compatibility layer, or `AgentRunner` integration.
- Do not make artifact refs mandatory when a subagent has no artifact output.
- Do not publish, quarantine-release, migrate, archive, or delete historical data automatically.
- Do not change the canonical Research artifact URI format or duplicate artifact bytes into subagent transcripts.

## Decisions

### 1. Define a framework-owned read-only verifier port

`ArtifactReferenceVerifierPort.verify_artifact_ref(ref, expected_run_id=...)` is a structural Harness port. It returns no payload and succeeds only after the canonical owner has checked the ref. `TaskPlanResultVerifier` and `TaskPlanReplayReducer` accept the port explicitly. Non-empty refs with no verifier fail closed; an empty tuple remains valid.

This keeps framework code independent from Research infrastructure. Using `ArtifactPort.read_artifact()` directly was rejected because that method exposes payloads and combines integrity with publication visibility.

### 2. Let the Research artifact owner verify pre-publication integrity

`FilesystemHarnessArtifactPort` implements the verifier by parsing the canonical ref, enforcing `expected_run_id`, reading the manifest through `ArtifactManager`, and invoking the existing internal payload-integrity path. The method discards the validated payload and does not consult or modify accepted-run publication state.

Creating a second artifact index or a TaskPlan-owned resolver was rejected because it would create competing ownership and duplicate checksum rules.

### 3. Verify at both acceptance and replay boundaries

The TaskPlan result verifier resolves artifact refs after transcript/output identity equality and before any `TaskResultRecord` is returned. Replay verifies that the durable output and result carry the same refs and resolves each ref again. Any verifier exception is mapped to the stable TaskPlan reason `task_plan_subagent_artifact_unverified` without embedding a raw backend exception.

This deliberately repeats I/O: acceptance proves the control transition was valid at commit time, while replay proves the evidence remains readable now.

### 4. Use the existing TaskPlan halt path for parent evidence

Artifact or transcript verification exceptions propagate as `HarnessValidationError`. `TaskPlanStageRunner` records `TASK_PLAN_HALTED` before returning a blocked result. Tests assert that no `TASK_RESULT_ACCEPTED` or `TASK_RESULT_REJECTED` record is appended for an unverified candidate.

### 5. Treat historical SQLite files as operator-owned orphaned data

A versioned operations release note names the retired default path, labels it `orphaned historical data`, states that NewsRoom no longer reads or creates it, and forbids automatic deletion. Operators decide whether to retain, archive, or remove it after their own retention review. An architecture test protects both the note and the absence of production create/delete code.

## Risks / Trade-offs

- [Artifact verification adds storage reads to acceptance and replay] -> Keep refs bounded by the transcript contract and reuse the canonical manifest/checksum path rather than adding another scan.
- [Integrity verification bypasses terminal visibility checks] -> Return no payload, enforce exact parent-run binding, and leave all normal readers on `read_artifact()` with the existing publication authorization.
- [A future artifact backend lacks the verifier] -> Fail closed for non-empty subagent refs until that backend implements the explicit port; artifact-free subagent results remain unaffected.
- [Historical files contain data subject to local retention rules] -> Never auto-delete; provide a clear operator decision boundary and no runtime migration logic.

## Migration Plan

1. Add and test the verifier contract and Research adapter.
2. Inject the verifier into production Research TaskPlan result verification and any replay construction that consumes subagent artifact refs.
3. Add adversarial acceptance/replay/parent-halt tests and filesystem tamper/run-binding tests.
4. Publish the retirement release note and architecture guard.
5. Run targeted tests, compile, mandatory smoke, and strict OpenSpec validation.
6. Mark the phase-27 PRD complete only after all gates pass, then archive this corrective change with spec synchronization.

Rollback reverts this change as one unit. It must not restore the retired session runtime; if artifact verification causes an operational failure, dynamic subagent results with artifact refs remain halted until the canonical artifact owner is repaired.

## Open Questions

None. The existing Research artifact owner and TaskPlan halt path provide the required boundaries.
