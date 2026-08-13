## 1. Canonical Artifact Verification Contract

- [x] 1.1 Add a read-only `ArtifactReferenceVerifierPort` to Harness artifact contracts and export it without coupling framework code to Research infrastructure.
- [x] 1.2 Implement parent-run-bound, manifest/checksum/size/bytes verification in `FilesystemHarnessArtifactPort` without exposing payload or granting publication visibility.
- [x] 1.3 Add adapter contract tests for valid refs, missing refs, cross-run refs, malformed refs, and tampered bytes.

## 2. TaskPlan Acceptance And Replay

- [x] 2.1 Inject the artifact verifier into `TaskPlanResultVerifier`; accept empty artifact tuples and fail closed on non-empty unverified refs with stable reason codes.
- [x] 2.2 Inject the verifier into `TaskPlanReplayReducer` and revalidate recorded subagent artifact refs without live calls.
- [x] 2.3 Wire the production Research artifact owner into dynamic TaskPlan result verification and prove composition does not use a fake or string-only verifier.
- [x] 2.4 Add adversarial TaskPlan tests for fabricated refs, missing verifier, valid verifier, replay tamper, and durable parent `TASK_PLAN_HALTED` evidence with no TaskResult append.

## 3. Retirement Operations Boundary

- [x] 3.1 Add a release/operations note that classifies legacy session SQLite files as `orphaned historical data`, forbids automatic access/deletion, and assigns retention decisions to operators.
- [x] 3.2 Add architecture/source tests that prevent production recreation or automatic deletion of the retired database and protect the operations note.

## 4. PRD And Verification

- [x] 4.1 Update the phase-27 PRD metadata, traceability, acceptance evidence, and Definition of Done after implementation gates pass.
- [x] 4.2 Record requirement-level evidence for this corrective change.
- [x] 4.3 Run focused Harness/Research/architecture tests and `./.venv/Scripts/python.exe -m scripts.dev compile`.
- [x] 4.4 Run mandatory `./.venv/Scripts/python.exe -m scripts.dev smoke`, `openspec validate close-subagent-artifact-evidence-and-retirement-docs --strict`, and `openspec validate --all --strict`.
- [x] 4.5 Audit every phase-27 PRD requirement against live code, tests, OpenSpec archives, release evidence, and commits before marking the work complete.
