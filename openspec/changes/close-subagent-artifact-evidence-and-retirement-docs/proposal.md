## Why

The completed Agent Session retirement work still accepts a subagent artifact URI when the transcript and worker result merely agree on the same string; the referenced artifact is not resolved through its canonical owner before TaskPlan acceptance or offline replay. The retirement PRD also requires operator-owned handling for historical SQLite session data, but no release/runbook artifact records that boundary and the PRD still reports `NOT_STARTED`.

## What Changes

- Add a Harness-owned read-only artifact-reference verifier contract and require every non-empty subagent artifact ref to resolve with the accepted parent run identity before TaskPlan result acceptance.
- Re-run the same canonical artifact integrity verification during offline TaskPlan replay, with a stable fail-closed reason when the verifier is absent or the artifact is missing, cross-run, malformed, or corrupt.
- Make the Research filesystem artifact adapter verify run binding, manifest metadata, checksum, size, and stored bytes without exposing pre-publication payloads.
- Prove transcript/artifact verification failures produce a durable parent `TASK_PLAN_HALTED` transition and never append an accepted/rejected TaskResult for an unverified candidate.
- Publish an operator release note that classifies pre-retirement `.newsroom/paper-agent-sessions.sqlite3` files as `orphaned historical data`, forbids automatic creation/deletion, and leaves archive/removal to an explicit operator decision.
- Update the phase-27 PRD metadata and Definition of Done only after the corrective change and mandatory gates pass.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `harness-runtime`: Close canonical ownership and replay verification for subagent artifact references.
- `harness-task-plan`: Require non-empty subagent artifact refs to be resolved before result acceptance and again during replay.
- `legacy-runtime-cleanup`: Define the no-auto-delete operator boundary for historical agent-session SQLite data.

## Impact

- Framework contracts and verification: `framework/harness/artifacts/**`, `framework/harness/task_plan/verification.py`, and `framework/harness/task_plan/replay.py`.
- Production adapter and composition: `infrastructure/research/artifact_port.py` and `interfaces/composition/research.py`.
- Tests: TaskPlan subagent lineage/replay, Research artifact integrity/composition, architecture cleanup, and parent halt evidence.
- Operations and source-of-truth docs: a retirement release note plus `docs/prd/harness-research-runtime/27-agent-session-retirement-and-subagent-transcript-durability.md`.
